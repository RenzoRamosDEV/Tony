"""ConversationRunner adapter over the `codex` CLI (design.md D2/D4): front sessions.

Each turn spawns its own `codex exec`/`codex exec resume <session_id>` subprocess with
its own `mcp-gateway` process (design.md's per-turn lifecycle decision - no pooling),
through the same `ToolBarrier`/`BridgeServer` plumbing as `CodexCliRunner`.

Voice streaming degrades for this engine (documented Non-Goal, design.md): there is no
partial `on_speech` chunk during generation. `on_speech`/`on_text` are each called at
most once per turn, after the full structured reply is parsed.

Security policy (non-negotiable, see tasks.md): `-s read-only`, never
`--dangerously-bypass-approvals-and-sandbox` nor `--approve-for-me`. `-c
approval_policy=never` is not one of those: it only stops codex's own approval wait,
which `exec` can never satisfy (there is no interactive terminal to answer it), without
loosening the sandbox. Every tool call still crosses our own `ToolBarrier`/`ConfirmGate`
first, which is what actually allows, confirms or denies it.
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
from tony.core.runner.auth import account_env, codex_account_args, require_credentials
from tony.core.runner.conversation import FrontTurn
from tony.core.runner.front_prompt import build_front_system_prompt
from tony.core.runner.gateway_bridge import BridgeServer
from tony.core.runner.mcp_gateway import refs_from_catalog, write_refs
from tony.core.runner.portable_native import PortableNativeTools
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import TaskState, ToolBarrier, ToolCaller
from tony.core.runner.reply_mode import FrontReply
from tony.core.runner.strict_schema import strict_schema

FRONT_OWNER_ID = "front"
GATEWAY_MODULE = "tony.core.runner.mcp_gateway_main"
SANDBOX_MODE = "read-only"
APPROVAL_POLICY_OVERRIDE = "approval_policy=never"
TextCallback = Callable[[str], Awaitable[None]]
TURN_FAILED = "No pude completar el turno: la salida de codex no cumple el esquema. {diagnostic}"
NO_RESULT_EVENT = "codex no devolvió ningún mensaje final"
APPROVAL_BLOCKED = "Codex bloqueó la llamada a la herramienta por su propia política de aprobación."


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
        await require_credentials(self._settings.engines[spec.engine])
        self._spec = spec
        self._native = PortableNativeTools(spec.tools.native, handlers, events)
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
            if qualified in self._native.catalog:
                return await self._native.call(qualified, args)
            return await barrier.handler(qualified)(args)

        with tempfile.TemporaryDirectory(prefix="tony-codex-turn-") as tmp:
            tmp_dir = Path(tmp)
            schema_path = tmp_dir / "schema.json"
            schema_path.write_text(json.dumps(strict_schema(FrontReply)), encoding="utf-8")
            catalog_path = tmp_dir / "catalog.json"
            write_refs(catalog_path, refs_from_catalog(self._catalog.merge(self._native.catalog)))
            socket_path = tmp_dir / "gateway.sock"
            if self.session_id is None:
                prompt = (
                    f"{build_front_system_prompt(self._spec, self._spec.tools.native)}\n\n{prompt}"
                )
            argv = self._build_argv(schema_path, socket_path, catalog_path, prompt)
            async with BridgeServer(socket_path, dispatch):
                stdout, stderr = await self._run_subprocess(argv)
        return await self._finish_turn(stdout, on_text, on_speech, stderr)

    def _build_argv(
        self, schema_path: Path, socket_path: Path, catalog_path: Path, prompt: str
    ) -> list[str]:
        gateway_command = json.dumps(sys.executable)
        gateway_args = json.dumps(
            ["-m", GATEWAY_MODULE, "--socket", str(socket_path), "--catalog", str(catalog_path)]
        )
        profile = self._settings.engines[self._spec.engine]
        base = [
            *self._codex_command,
            *codex_account_args(profile),
            "-s",
            SANDBOX_MODE,
            "-c",
            APPROVAL_POLICY_OVERRIDE,
            "exec",
        ]
        if profile.auth == "account":
            self._env = account_env("codex_cli", self._env)
        if self.session_id is not None:
            base += ["resume", self.session_id]
        return [
            *base,
            "--json",
            "--output-schema",
            str(schema_path),
            "-c",
            f"mcp_servers.tony.command={gateway_command}",
            "-c",
            f"mcp_servers.tony.args={gateway_args}",
            prompt,
        ]

    async def _run_subprocess(self, argv: list[str]) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )

    async def _finish_turn(
        self,
        stdout: str,
        on_text: TextCallback | None,
        on_speech: TextCallback | None,
        stderr: str = "",
    ) -> FrontTurn:
        session_id, payload, found_message = self._last_agent_message(stdout)
        if session_id is not None:
            self.session_id = session_id
        if "requires approval" in stdout or "requires approval" in stderr:
            return FrontTurn(text=APPROVAL_BLOCKED, error=APPROVAL_BLOCKED)
        if not found_message:
            return FrontTurn(text=NO_RESULT_EVENT, error=NO_RESULT_EVENT)
        try:
            reply = FrontReply.model_validate(json.loads(payload))
        except Exception as exc:  # noqa: BLE001 - any schema mismatch becomes a failed turn
            diagnostic = f"{exc.__class__.__name__}: {exc}"
            return FrontTurn(text=TURN_FAILED.format(diagnostic=diagnostic), error=diagnostic)
        if on_text is not None:
            await on_text(reply.display_text)
        if on_speech is not None:
            await on_speech(reply.speech_text or reply.display_text)
        return FrontTurn(text=reply.display_text, structured=reply.model_dump())

    @staticmethod
    def _last_agent_message(stdout: str) -> tuple[str | None, Any, bool]:
        session_id: str | None = None
        payload: Any = None
        found_message = False
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id")
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
            ):
                found_message = True
                payload = item.get("text")
        return session_id, payload, found_message

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None
