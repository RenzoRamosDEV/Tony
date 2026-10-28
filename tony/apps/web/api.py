"""JSON API under /api: thin translation to the hub, the runtime and the memory stores."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from tony import __version__
from tony.apps.web.confirmations import InvalidConfirmation
from tony.apps.web.hub import ConversationHub
from tony.core.channels.bootstrap import ChatRuntime
from tony.core.config import ReplyMode
from tony.core.orchestrator.errors import OrchestratorError

router = APIRouter(prefix="/api")

STATUS_CODES = {"unknown_task": 404, "invalid_confirmation": 409}
HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed", 403: "forbidden_origin"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


class SettingsPatch(BaseModel):
    reply_mode: ReplyMode


class ConfirmBody(BaseModel):
    confirmation_id: str
    approved: bool


def error_response(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


def hub_of(request: Request) -> ConversationHub:
    return request.app.state.hub


def runtime_of(request: Request) -> ChatRuntime:
    return request.app.state.runtime


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    statuses = runtime.worker_factory.status()
    return {
        "status": "ok",
        "version": __version__,
        "front": runtime.front.name,
        "worker": runtime.worker.name,
        "mcp": [
            {"name": name, "state": status.state, "tool_count": status.tool_count}
            for name, status in statuses.items()
        ],
        "voice": hub_of(request).voice.availability.as_dict(),
    }


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    persisted = runtime.memory.settings.load().reply_mode
    if persisted is not None:
        return {"reply_mode": persisted, "reply_mode_source": "settings"}
    return {"reply_mode": runtime.settings.reply_mode, "reply_mode_source": "yaml"}


@router.patch("/settings")
async def patch_settings(request: Request, body: SettingsPatch) -> dict[str, Any]:
    runtime_of(request).memory.settings.set_reply_mode(body.reply_mode)
    return {"reply_mode": body.reply_mode, "reply_mode_source": "settings"}


@router.post("/tasks/{task_id}/confirm")
async def confirm_task(request: Request, task_id: str, body: ConfirmBody) -> dict[str, Any]:
    hub = hub_of(request)
    assert hub.router is not None
    try:
        await hub.router.resolve(body.confirmation_id, body.approved, task_id)
    except InvalidConfirmation as exc:
        raise ApiError(409, exc.code, exc.detail) from None
    return {"ok": True}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
    try:
        await hub_of(request).cancel_task(task_id)
    except OrchestratorError as exc:
        raise ApiError(
            STATUS_CODES.get(exc.code, 400), exc.code, f"la tarea {task_id} no existe"
        ) from None
    return {"ok": True}


@router.get("/conversations")
async def list_conversations(request: Request) -> list[dict[str, Any]]:
    store = runtime_of(request).memory.conversations
    return [
        {"id": c.id, "channel": c.channel, "created_at": c.created_at}
        for c in store.list_conversations()
    ]


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(request: Request, conversation_id: str) -> list[dict[str, Any]]:
    store = runtime_of(request).memory.conversations
    if not store.has_conversation(conversation_id):
        raise ApiError(404, "unknown_conversation", f"la conversación {conversation_id} no existe")
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "reply_mode": m.reply_mode,
            "created_at": m.created_at,
        }
        for m in store.messages(conversation_id)
    ]


@router.get("/memory")
async def memory(request: Request) -> dict[str, Any]:
    preferences = runtime_of(request).memory.preferences
    content = preferences.path.read_text(encoding="utf-8") if preferences.path.exists() else ""
    return {"content": content, "lines": len(preferences.read())}


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.detail)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(422, "validation_error", _validation_detail(exc))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, str(exc.detail))


def _validation_detail(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
        parts.append(f"{location or 'cuerpo'}: {error.get('msg', 'inválido')}")
    return "; ".join(parts) or "cuerpo inválido"
