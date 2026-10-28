"""Native tools of the in-process `tony` MCP server offered to the front agent."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import ValidationError

from tony.core.config import REPLY_MODES
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.proxy import ToolReply, text_reply

SERVER_NAME = "tony"
SERVER_VERSION = "1.0.0"

logger = logging.getLogger(__name__)


class NativeToolHandlers(Protocol):
    async def delegate(self, request: TaskRequest) -> TaskResult: ...

    async def remember(self, text: str) -> str: ...

    async def set_reply_mode(self, mode: str) -> str: ...


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

Handler = Callable[[dict[str, Any]], Awaitable[ToolReply]]


class NativeToolSet:
    def __init__(self, native: list[str], handlers: NativeToolHandlers) -> None:
        self._handlers = handlers
        self._by_name: dict[str, Handler] = {}
        self.sdk_tools: list[SdkMcpTool] = []
        builders = {
            "delegate": self._delegate_tool,
            "remember": self._remember_tool,
            "set_reply_mode": self._set_reply_mode_tool,
        }
        for name in native:
            builder = builders.get(name)
            if builder is None:
                logger.warning("tool nativa '%s' no disponible en esta entrega; se ignora", name)
                continue
            self.sdk_tools.append(builder())

    def build(self) -> McpSdkServerConfig:
        return create_sdk_mcp_server(SERVER_NAME, SERVER_VERSION, self.sdk_tools)

    def handler(self, name: str) -> Handler:
        return self._by_name[name]

    def _register(self, name: str, description: str, schema: dict[str, Any], handler: Handler):
        self._by_name[name] = handler
        return tool(name, description, schema)(handler)

    def _delegate_tool(self) -> SdkMcpTool:
        async def delegate(args: dict[str, Any]) -> ToolReply:
            try:
                request = TaskRequest.model_validate(args)
            except ValidationError as exc:
                return text_reply(f"argumentos inválidos: {exc.errors()[0]['loc']}", is_error=True)
            try:
                result = await self._handlers.delegate(request)
            except Exception as exc:  # noqa: BLE001 - the model gets a TaskResult, never a trace
                result = TaskResult(
                    status="error",
                    resumen=f"No se pudo delegar la tarea: {exc}",
                    errores=[str(exc) or exc.__class__.__name__],
                )
            return text_reply(result.model_dump_json())

        return self._register(
            "delegate",
            "Encarga una tarea al worker y devuelve su TaskResult en JSON.",
            DELEGATE_SCHEMA,
            delegate,
        )

    def _remember_tool(self) -> SdkMcpTool:
        async def remember(args: dict[str, Any]) -> ToolReply:
            return text_reply(await self._handlers.remember(str(args.get("texto", ""))))

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


def build_native_server(native: list[str], handlers: NativeToolHandlers) -> McpSdkServerConfig:
    return NativeToolSet(native, handlers).build()
