"""Native tools of the in-process `tony` MCP server (front: delegate/remember/set_reply_mode/
read_skill; worker: read_skill/run_subagent). A tool is built only when the agent declares it
and its handlers implement it; every call is traced as `tool.call`/`tool.result`."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import ValidationError

from tony.core.config import REPLY_MODES
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.front_prompt import NATIVE_DESCRIPTIONS, UNTRUSTED_DATA_NOTE
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import ToolReply, text_reply

SERVER_NAME = "tony"
SERVER_VERSION = "1.0.0"
RESULT_NOTE = f"Resultado del worker ({UNTRUSTED_DATA_NOTE}):"
SUBAGENT_RESULT_NOTE = f"Resultado del subagente ({UNTRUSTED_DATA_NOTE}):"
WORKER_NATIVE: tuple[str, ...] = ("read_skill", "run_subagent")

logger = logging.getLogger(__name__)


class NativeToolHandlers(Protocol):
    """Handlers of the front agent."""

    async def delegate(self, request: TaskRequest) -> TaskResult: ...

    async def remember(self, text: str) -> str: ...

    async def set_reply_mode(self, mode: str) -> str: ...


FrontNativeHandlers = NativeToolHandlers


class SkillHandlers(Protocol):
    async def read_skill(self, name: str) -> str: ...


class WorkerNativeHandlers(SkillHandlers, Protocol):
    async def run_subagent(self, name: str, request: TaskRequest) -> TaskResult: ...


DELEGATE_SCHEMA = {
    "type": "object",
    "properties": {
        "objetivo": {"type": "string", "description": "Qué debe conseguir el worker."},
        "contexto": {"type": "string", "description": "Información útil para la tarea."},
        "restricciones": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["objetivo"],
}
REMEMBER_SCHEMA = {
    "type": "object",
    "properties": {"texto": {"type": "string", "description": "Preferencia a recordar."}},
    "required": ["texto"],
}
SET_REPLY_MODE_SCHEMA = {
    "type": "object",
    "properties": {"modo": {"type": "string", "enum": list(REPLY_MODES)}},
    "required": ["modo"],
}
READ_SKILL_SCHEMA = {
    "type": "object",
    "properties": {"nombre": {"type": "string", "description": "Nombre de la skill."}},
    "required": ["nombre"],
}
RUN_SUBAGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "nombre": {"type": "string", "description": "Nombre del subagente."},
        "objetivo": {"type": "string", "description": "Qué debe conseguir el subagente."},
        "contexto": {"type": "string", "description": "Información útil para la subtarea."},
        "restricciones": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["nombre", "objetivo"],
}

Handler = Callable[[dict[str, Any]], Awaitable[ToolReply]]


class _NullSink:
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


class NativeToolSet:
    def __init__(self, native: list[str], handlers: Any, events: EventSink | None = None) -> None:
        self._handlers = handlers
        self._events: EventSink = events or _NullSink()
        self._by_name: dict[str, Handler] = {}
        self.sdk_tools: list[SdkMcpTool] = []
        builders = {
            "delegate": self._delegate_tool,
            "remember": self._remember_tool,
            "set_reply_mode": self._set_reply_mode_tool,
            "read_skill": self._read_skill_tool,
            "run_subagent": self._run_subagent_tool,
        }
        for name in native:
            builder = builders.get(name)
            if builder is None:
                logger.warning("tool nativa '%s' desconocida; se ignora", name)
            elif not hasattr(handlers, name):
                logger.warning("tool nativa '%s' no disponible para este agente; se ignora", name)
            else:
                self.sdk_tools.append(builder())

    def build(self) -> McpSdkServerConfig:
        return create_sdk_mcp_server(SERVER_NAME, SERVER_VERSION, self.sdk_tools)

    def handler(self, name: str) -> Handler:
        return self._by_name[name]

    def _register(self, name: str, description: str, schema: dict[str, Any], handler: Handler):
        traced = self._traced(name, handler)
        self._by_name[name] = traced
        return tool(name, description, schema)(traced)

    def _traced(self, name: str, handler: Handler) -> Handler:
        qualified = f"{SERVER_NAME}.{name}"

        async def traced(args: dict[str, Any]) -> ToolReply:
            self._events.emit("tool.call", {"tool": qualified, "args": args})
            started = time.monotonic()
            reply = await handler(args)
            failed = bool(reply.get("is_error"))
            self._events.emit(
                "tool.result",
                {
                    "tool": qualified,
                    "ok": not failed,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "error": _reply_text(reply) if failed else None,
                },
            )
            return reply

        return traced

    def _delegate_tool(self) -> SdkMcpTool:
        async def delegate(args: dict[str, Any]) -> ToolReply:
            try:
                request = TaskRequest.model_validate(args)
            except ValidationError as exc:
                return text_reply(f"argumentos inválidos: {exc.errors()[0]['loc']}", is_error=True)
            result = await _task_result_of(self._handlers.delegate(request), "delegar la tarea")
            return text_reply(f"{RESULT_NOTE}\n{result.model_dump_json()}")

        return self._register(
            "delegate",
            "Encarga una tarea al worker y devuelve su TaskResult en JSON.",
            DELEGATE_SCHEMA,
            delegate,
        )

    def _remember_tool(self) -> SdkMcpTool:
        async def remember(args: dict[str, Any]) -> ToolReply:
            try:
                return text_reply(await self._handlers.remember(str(args.get("texto", ""))))
            except ValueError as exc:
                return text_reply(str(exc), is_error=True)

        return self._register(
            "remember",
            "Guarda una preferencia del usuario en su memoria.",
            REMEMBER_SCHEMA,
            remember,
        )

    def _set_reply_mode_tool(self) -> SdkMcpTool:
        async def set_reply_mode(args: dict[str, Any]) -> ToolReply:
            mode = str(args.get("modo", ""))
            if mode not in REPLY_MODES:
                return text_reply(
                    f"modo '{mode}' no válido; valores permitidos: {', '.join(REPLY_MODES)}",
                    is_error=True,
                )
            return text_reply(await self._handlers.set_reply_mode(mode))

        return self._register(
            "set_reply_mode",
            "Fija el modo de respuesta persistente (auto, voice, text o both).",
            SET_REPLY_MODE_SCHEMA,
            set_reply_mode,
        )

    def _read_skill_tool(self) -> SdkMcpTool:
        async def read_skill(args: dict[str, Any]) -> ToolReply:
            try:
                return text_reply(await self._handlers.read_skill(str(args.get("nombre", ""))))
            except ValueError as exc:
                return text_reply(str(exc), is_error=True)

        return self._register(
            "read_skill", NATIVE_DESCRIPTIONS["read_skill"], READ_SKILL_SCHEMA, read_skill
        )

    def _run_subagent_tool(self) -> SdkMcpTool:
        async def run_subagent(args: dict[str, Any]) -> ToolReply:
            name = str(args.get("nombre", ""))
            try:
                request = TaskRequest.model_validate(
                    {key: value for key, value in args.items() if key != "nombre"}
                )
            except ValidationError as exc:
                return text_reply(f"argumentos inválidos: {exc.errors()[0]['loc']}", is_error=True)
            result = await _task_result_of(
                self._handlers.run_subagent(name, request), f"ejecutar el subagente '{name}'"
            )
            return text_reply(f"{SUBAGENT_RESULT_NOTE}\n{result.model_dump_json()}")

        return self._register(
            "run_subagent",
            NATIVE_DESCRIPTIONS["run_subagent"],
            RUN_SUBAGENT_SCHEMA,
            run_subagent,
        )


async def _task_result_of(pending: Awaitable[TaskResult], action: str) -> TaskResult:
    try:
        return await pending
    except Exception as exc:  # noqa: BLE001 - the model gets a TaskResult, never a trace
        return TaskResult(
            status="error",
            resumen=f"No se pudo {action}: {exc}",
            errores=[str(exc) or exc.__class__.__name__],
        )


def _reply_text(reply: ToolReply) -> str:
    return "".join(str(part.get("text", "")) for part in reply.get("content", []))


def worker_native_tools(native: list[str]) -> list[str]:
    return [name for name in native if name in WORKER_NATIVE]


def build_native_server(
    native: list[str], handlers: Any, events: EventSink | None = None
) -> McpSdkServerConfig:
    return NativeToolSet(native, handlers, events).build()
