"""AgentRunner adapter over the `codex` CLI (design.md D2/D4): one task, one gateway.

`codex exec` is invoked with `--output-schema` pointed at `TaskResult`'s JSON Schema
and with Codex's own MCP client wired (`-c mcp_servers.tony.*`) at an `mcp-gateway`
subprocess (`mcp_gateway_main`) that forwards every tool call back to this process's
`ToolBarrier`, via `BridgeServer`/`BridgeClient` (`gateway_bridge.py`), over a Unix
socket. The barrier itself - allow, confirm, timeout, log - is the exact same object
`ClaudeSdkRunner` would build; only the transport to reach it differs.

Security policy (non-negotiable, see tasks.md): `-s read-only`, never
`--dangerously-bypass-approvals-and-sandbox` nor `--approve-for-me`.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.runner.auth import account_env, codex_account_args, require_credentials
from tony.core.runner.cancel import CancelToken
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.gateway_bridge import BridgeServer
from tony.core.runner.mcp_gateway import refs_from_catalog, write_refs
from tony.core.runner.portable_native import PortableNativeTools
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import TaskState, ToolBarrier, ToolCaller
from tony.core.runner.results import error_result
from tony.core.runner.strict_schema import strict_schema

GATEWAY_MODULE = "tony.core.runner.mcp_gateway_main"
SANDBOX_MODE = "read-only"
INVALID_STRUCTURED_OUTPUT = "la salida de codex no cumple el esquema de TaskResult"
NO_RESULT_EVENT = "codex no devolvió ningún mensaje final"
APPROVAL_BLOCKED = "Codex bloqueó la llamada a la herramienta por su propia política de aprobación."


def codex_cli_runner_factory(
    settings: TonySettings,
    task_id: str,
    gate: ConfirmGate,
    call: ToolCaller,
    token: CancelToken,
    native_handlers: Any = None,
) -> CodexCliRunner:
    return CodexCliRunner(
        settings=settings,
        task_id=task_id,
        gate=gate,
        call=call,
        cancel_token=token,
        native_handlers=native_handlers,
    )


class CodexCliRunner:
    def __init__(
        self,
        settings: TonySettings,
        task_id: str,
        gate: ConfirmGate,
        call: ToolCaller,
        codex_command: list[str] | None = None,
        env: dict[str, str] | None = None,
        cancel_token: CancelToken | None = None,
        native_handlers: Any = None,
    ) -> None:
        self._settings = settings
        self._task_id = task_id
        self._gate = gate
        self._call = call
        self._codex_command = codex_command or ["codex"]
        self._auth_args: list[str] = []
        self._env = env
        self._cancel_token = cancel_token
        self._native_handlers = native_handlers

    def _build_argv(
        self, schema_path: Path, socket_path: Path, catalog_path: Path, prompt: str
    ) -> list[str]:
        gateway_command = json.dumps(sys.executable)
        gateway_args = json.dumps(
            ["-m", GATEWAY_MODULE, "--socket", str(socket_path), "--catalog", str(catalog_path)]
        )
        return [
            *self._codex_command,
            *self._auth_args,
            "exec",
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

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        profile = self._settings.engines[spec.engine]
        await require_credentials(profile)
        self._auth_args = codex_account_args(profile)
        if profile.auth == "account":
            self._env = account_env("codex_cli", self._env)
        events.emit("task.started", {"agent": spec.name, **request.model_dump()})
        native = PortableNativeTools(spec.tools.native, self._native_handlers, events)
        limits = self._settings.limits
        state = TaskState(self._task_id, cancel_token=self._cancel_token or CancelToken())
        barrier = ToolBarrier(
            tools,
            self._call,
            self._gate,
            events,
            state,
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        )

        async def dispatch(qualified: str, args: dict[str, Any]) -> dict[str, Any]:
            if qualified in native.catalog:
                return await native.call(qualified, args)
            return await barrier.handler(qualified)(args)

        with tempfile.TemporaryDirectory(prefix="tony-codex-") as tmp:
            tmp_dir = Path(tmp)
            schema_path = tmp_dir / "schema.json"
            schema_path.write_text(json.dumps(strict_schema(TaskResult)), encoding="utf-8")
            catalog_path = tmp_dir / "catalog.json"
            write_refs(catalog_path, refs_from_catalog(tools.merge(native.catalog)))
            socket_path = tmp_dir / "gateway.sock"
            prompt = f"{spec.system_prompt}\n\n{request.objetivo}\n\n{request.contexto}".strip()
            argv = self._build_argv(schema_path, socket_path, catalog_path, prompt)
            async with BridgeServer(socket_path, dispatch):
                stdout, stderr, returncode = await self._run_subprocess(argv)
        result = self._parse_result(stdout, state, stderr)
        events.emit("task.finished", {"status": result.status, "usage": {}})
        return result

    async def _run_subprocess(self, argv: list[str]) -> tuple[str, str, int]:
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
            proc.returncode or 0,
        )

    def _parse_result(self, stdout: str, state: TaskState, stderr: str = "") -> TaskResult:
        if "requires approval" in stdout or "requires approval" in stderr:
            return error_result(APPROVAL_BLOCKED, state.steps)
        payload = None
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
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
            ):
                found_message = True
                payload = item.get("text")
        if not found_message:
            return error_result(NO_RESULT_EVENT, state.steps)
        try:
            return TaskResult.model_validate(json.loads(payload))
        except Exception:  # noqa: BLE001 - any schema mismatch becomes an error TaskResult
            return error_result(INVALID_STRUCTURED_OUTPUT, state.steps)
