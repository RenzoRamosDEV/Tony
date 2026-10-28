"""FastAPI app of `tony web`: Origin policy, JSON API, /ws/chat and the compiled frontend."""

from __future__ import annotations

import logging
import sys
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from tony.apps.web import api
from tony.apps.web.hub import ConversationHub, error_envelope
from tony.apps.web.options import WebOptions
from tony.apps.web.protocol import CLOSE_POLICY_VIOLATION, ProtocolError, parse_client_message
from tony.apps.web.voice import VoiceRuntime
from tony.core.channels.bootstrap import ChatRuntime, build_chat_runtime
from tony.core.orchestrator.clock import SystemClock

MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
LOOPBACK_ALIASES = ("127.0.0.1", "localhost")
WS_MAX_SIZE = 65536
DEFAULT_DIST = Path(__file__).parent / "frontend" / "dist"
FALLBACK_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Tony</title></head>
<body style="font-family: system-ui; max-width: 60ch; margin: 3rem auto; line-height: 1.5">
<h1>Tony: chat web sin compilar</h1>
<p>El servidor funciona, pero el frontend no está compilado. Compílalo y recarga:</p>
<pre>cd tony/apps/web/frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>La API sigue disponible en <code>/api/health</code>.</p>
</body></html>
"""
Boot = Callable[[], Awaitable[tuple[ConversationHub, ChatRuntime]]]
logger = logging.getLogger(__name__)


class OriginPolicy:
    """Closed list of allowed `Origin` values for mutating HTTP requests and WS upgrades."""

    def __init__(self, host: str, port: int) -> None:
        hosts = {host}
        if host in LOOPBACK_ALIASES:
            hosts.update(LOOPBACK_ALIASES)
        self.allowed = {f"http://{_bracketed(h)}:{port}" for h in hosts}

    def allows(self, origin: str | None) -> bool:
        return origin is not None and origin in self.allowed

    def guards(self, method: str) -> bool:
        return method.upper() in MUTATING_METHODS


def _bracketed(host: str) -> str:
    return f"[{host}]" if ":" in host else host


class OriginMiddleware:
    def __init__(self, app: ASGIApp, policy: OriginPolicy) -> None:
        self._app = app
        self._policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._policy.guards(scope["method"]):
            origin = _header(scope, b"origin")
            if not self._policy.allows(origin):
                response = api.error_response(403, "forbidden_origin", _forbidden_detail(origin))
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _forbidden_detail(origin: str | None) -> str:
    return f"Origin '{origin}' no permitido" if origin else "falta la cabecera Origin"


def create_app(
    boot: Boot, options: WebOptions, open_url: Callable[[str], Any] | None = None
) -> FastAPI:
    policy = OriginPolicy(options.host, options.port)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub, runtime = await boot()
        app.state.hub, app.state.runtime = hub, runtime
        if options.open_browser:
            (open_url or open_in_browser)(options.url)
        try:
            yield
        finally:
            try:
                await hub.aclose()
            finally:
                await runtime.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(OriginMiddleware, policy=policy)
    app.add_exception_handler(api.ApiError, api.api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, api.validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, api.http_exception_handler)  # type: ignore[arg-type]
    app.include_router(api.router)
    app.add_api_websocket_route("/ws/chat", _chat_socket(policy))
    _mount_frontend(app, options.dist_dir or DEFAULT_DIST)
    return app


def _chat_socket(policy: OriginPolicy) -> Callable[[WebSocket], Awaitable[None]]:
    async def chat_socket(websocket: WebSocket) -> None:
        if not policy.allows(websocket.headers.get("origin")):
            await websocket.close(code=CLOSE_POLICY_VIOLATION)
            return
        await websocket.accept()
        hub: ConversationHub = websocket.app.state.hub
        try:
            while True:
                received = await websocket.receive()
                if received["type"] == "websocket.disconnect":
                    return
                if received.get("bytes") is not None:
                    await hub.audio_frame(websocket, received["bytes"])
                    continue
                try:
                    message = parse_client_message(received.get("text") or "")
                except ProtocolError as exc:
                    envelope = error_envelope(exc.code, exc.detail, hub.conversation_id)
                    await websocket.send_text(envelope.to_json())
                    if exc.close_code is not None:
                        await websocket.close(code=exc.close_code)
                        return
                    continue
                await hub.dispatch(websocket, message)
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            hub.detach(websocket)

    return chat_socket


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    async def root() -> Any:
        if index.is_file():
            return FileResponse(index, media_type="text/html")
        return HTMLResponse(FALLBACK_PAGE)


def open_in_browser(url: str) -> None:
    webbrowser.open(url)


async def serve(options: WebOptions, **factories: Any) -> None:
    """Build the runtime in the current loop, then run uvicorn on it until SIGINT/SIGTERM."""
    hub = ConversationHub(SystemClock())
    runtime = await build_chat_runtime(
        options.runtime, hub.gate_factory, err=sys.stderr, **factories
    )
    hub.bind(runtime, VoiceRuntime.detect(runtime.settings.voice))

    async def boot() -> tuple[ConversationHub, ChatRuntime]:
        return hub, runtime

    app = create_app(boot, options)
    config = uvicorn.Config(
        app, host=options.host, port=options.port, log_level="info", ws_max_size=WS_MAX_SIZE
    )
    await uvicorn.Server(config).serve()
