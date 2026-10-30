"""ConversationRunner adapter over the `codex` CLI (design.md D2/D4): front sessions.

Each turn spawns its own `codex exec`/`codex exec resume <session_id>` subprocess with
its own `mcp-gateway` process (design.md's per-turn lifecycle decision - no pooling),
through the same `ToolBarrier`/`BridgeServer` plumbing as `CodexCliRunner`.

Voice streaming degrades for this engine (documented Non-Goal, design.md): there is no
partial `on_speech` chunk during generation. `on_speech`/`on_text` are each called at
most once per turn, after the full structured reply is parsed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.runner.conversation import FrontTurn
from tony.core.runner.gateway_bridge import BridgeServer
from tony.core.runner.mcp_gateway import refs_from_catalog, write_refs
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import TaskState, ToolBarrier, ToolCaller
from tony.core.runner.reply_mode import FrontReply
from tony.core.runner.strict_schema import strict_schema

FRONT_OWNER_ID = "front"
GATEWAY_MODULE = "tony.core.runner.mcp_gateway_main"
SANDBOX_MODE = "read-only"
TextCallback = Callable[[str], Awaitable[None]]
TURN_FAILED = "No pude completar el turno: la salida de codex no cumple el esquema. {diagnostic}"
NO_RESULT_EVENT = "codex no devolvió ningún evento 'result'"


class CodexCliConversation:
    def __init__(
        self,
        settings: TonySettings,
        gate: ConfirmGate,
        call: ToolCaller,
        codex_command: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._gate = gate
        self._call = call
        self._codex_command = codex_command or ["codex"]
        self._env = env
        self._catalog: ToolCatalog = ToolCatalog()
        self._events: EventSink | None = None
        self._turn_state = TaskState(FRONT_OWNER_ID)
        self.session_id: str | None = None

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: Any,
        events: EventSink,
        resume: str | None = None,
    ) -> None:
        self._spec = spec
        self._catalog = catalog
        self._events = events
        self.session_id = resume

    async def turn(
        self,
        prompt: str,
        on_text: TextCallback | None = None,
        on_speech: TextCallback | None = None,
    ) -> FrontTurn:
        events = self._events
        assert events is not None, "la conversación no está abierta"
        limits = self._settings.limits
        self._turn_state = TaskState(FRONT_OWNER_ID, interrupt=self.interrupt)
        barrier = ToolBarrier(
            self._catalog,
            self._call,
            self._gate,
            events,
            self._turn_state,
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        )

        async def dispatch(qualified: str, args: dict[str, Any]) -> dict[str, Any]:
            return await barrier.handler(qualified)(args)

        with tempfile.TemporaryDirectory(prefix="tony-codex-turn-") as tmp:
            tmp_dir = Path(tmp)
            schema_path = tmp_dir / "schema.json"
            schema_path.write_text(json.dumps(strict_schema(FrontReply)), encoding="utf-8")
            catalog_path = tmp_dir / "catalog.json"
            write_refs(catalog_path, refs_from_catalog(self._catalog))
            socket_path = tmp_dir / "gateway.sock"
            argv = self._build_argv(schema_path, socket_path, catalog_path, prompt)
            async with BridgeServer(socket_path, dispatch):
                stdout = await self._run_subprocess(argv)
        return await self._finish_turn(stdout, on_text, on_speech)

    def _build_argv(
        self, schema_path: Path, socket_path: Path, catalog_path: Path, prompt: str
    ) -> list[str]:
        gateway_command = json.dumps(sys.executable)
        gateway_args = json.dumps(
            ["-m", GATEWAY_MODULE, "--socket", str(socket_path), "--catalog", str(catalog_path)]
        )
        base = [*self._codex_command, "exec"]
        if self.session_id is not None:
            base += ["resume", self.session_id]
        return [
            *base,
            "--json",
            "--output-schema",
            str(schema_path),
            "-s",
            SANDBOX_MODE,
            "-c",
            f"mcp_servers.tony.command={gateway_command}",
            "-c",
            f"mcp_servers.tony.args={gateway_args}",
            prompt,
        ]

    async def _run_subprocess(self, argv: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        stdout_bytes, _ = await proc.communicate()
        return stdout_bytes.decode("utf-8", errors="replace")

    async def _finish_turn(
        self, stdout: str, on_text: TextCallback | None, on_speech: TextCallback | None
    ) -> FrontTurn:
        session_id, payload = self._last_result_event(stdout)
        if session_id is not None:
            self.session_id = session_id
        if payload is None:
            return FrontTurn(text=NO_RESULT_EVENT, error=NO_RESULT_EVENT)
        try:
            reply = FrontReply.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - any schema mismatch becomes a failed turn
            diagnostic = f"{exc.__class__.__name__}: {exc}"
            return FrontTurn(text=TURN_FAILED.format(diagnostic=diagnostic), error=diagnostic)
        if on_text is not None:
            await on_text(reply.display_text)
        if on_speech is not None:
            await on_speech(reply.speech_text or reply.display_text)
        return FrontTurn(text=reply.display_text, structured=reply.model_dump())

    @staticmethod
    def _last_result_event(stdout: str) -> tuple[str | None, dict[str, Any] | None]:
        session_id: str | None = None
        payload: dict[str, Any] | None = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                session_id = event.get("session_id")
                payload = event.get("result")
        return session_id, payload

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None
