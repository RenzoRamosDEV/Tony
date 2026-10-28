"""In-process MCP servers that proxy catalog tools through Tony's execution barrier."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    McpSdkServerConfig,
    SdkMcpTool,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from tony.core.mcp import ConfirmGate, ConfirmRequest, ToolCallOutcome, ToolCatalog, ToolRef
from tony.core.runner.ports import EventSink

ToolCaller = Callable[[str, dict[str, Any], float], Awaitable[ToolCallOutcome]]
Interrupt = Callable[[], Awaitable[None]]
ToolReply = dict[str, Any]

NOT_CONFIRMED = "Tool {tool} no confirmada por el usuario"
TASK_CANCELLED = "Tarea cancelada; no se ejecuta {tool}"
PROXY_VERSION = "1.0.0"


@dataclass
class TaskState:
    task_id: str
    cancelled: bool = False
    cancel_reason: str | None = None
    steps: list[str] = field(default_factory=list)
    interrupt: Interrupt | None = None

    def cancel(self, tool: str) -> None:
        if not self.cancelled:
            self.cancelled = True
            self.cancel_reason = tool

    async def request_interrupt(self) -> None:
        if self.interrupt is None:
            return
        try:
            await self.interrupt()
        except Exception:  # noqa: BLE001 - interrupting is best effort
            pass


def text_reply(text: str, is_error: bool = False) -> ToolReply:
    reply: ToolReply = {"content": [{"type": "text", "text": text}]}
    if is_error:
        reply["is_error"] = True
    return reply


class ToolProxyFactory:
    def __init__(
        self,
        catalog: ToolCatalog,
        call: ToolCaller,
        gate: ConfirmGate,
        events: EventSink,
        task_state: TaskState,
        tool_timeout_s: float,
        confirm_timeout_s: float,
    ) -> None:
        self._call = call
        self._gate = gate
        self._events = events
        self._state = task_state
        self._tool_timeout_s = tool_timeout_s
        self._confirm_timeout_s = confirm_timeout_s
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[ToolReply]]] = {}
        self.sdk_tools: dict[str, list[SdkMcpTool]] = {
            server: [self._make_tool(ref) for ref in refs]
            for server, refs in catalog.servers().items()
        }

    def build(self) -> dict[str, McpSdkServerConfig]:
        return {
            server: create_sdk_mcp_server(server, PROXY_VERSION, tools)
            for server, tools in self.sdk_tools.items()
        }

    def handler(self, qualified: str) -> Callable[[dict[str, Any]], Awaitable[ToolReply]]:
        return self._handlers[qualified]

    def _make_tool(self, ref: ToolRef) -> SdkMcpTool:
        async def handler(args: dict[str, Any]) -> ToolReply:
            return await self._execute(ref, args)

        self._handlers[ref.qualified] = handler
        annotations = ToolAnnotations(destructiveHint=True) if ref.destructive else None
        schema = _sdk_input_schema(ref.input_schema)
        return tool(ref.name, ref.description, schema, annotations=annotations)(handler)

    async def _execute(self, ref: ToolRef, args: dict[str, Any]) -> ToolReply:
        qualified = ref.qualified
        self._events.emit("tool.call", {"tool": qualified, "args": args})
        if self._state.cancelled:
            return self._reject(qualified, TASK_CANCELLED.format(tool=qualified))
        if ref.needs_confirm and not await self._approved(qualified, args):
            self._state.cancel(qualified)
            await self._state.request_interrupt()
            return self._reject(qualified, NOT_CONFIRMED.format(tool=qualified))
        if self._state.cancelled:
            return self._reject(qualified, TASK_CANCELLED.format(tool=qualified))
        outcome = await self._call(qualified, args, self._tool_timeout_s)
        self._emit_result(qualified, outcome.ok, outcome.duration_ms, outcome.error)
        self._state.steps.append(_describe_step(qualified, args))
        if not outcome.ok:
            return text_reply(outcome.error or "error desconocido", is_error=True)
        return text_reply(outcome.content)

    async def _approved(self, qualified: str, args: dict[str, Any]) -> bool:
        request = ConfirmRequest.create(self._state.task_id, qualified, args)
        try:
            return await asyncio.wait_for(self._gate.confirm(request), self._confirm_timeout_s)
        except TimeoutError:
            return False

    def _reject(self, qualified: str, error: str) -> ToolReply:
        self._emit_result(qualified, ok=False, duration_ms=0, error=error)
        return text_reply(error, is_error=True)

    def _emit_result(self, tool_name: str, ok: bool, duration_ms: int, error: str | None) -> None:
        self._events.emit(
            "tool.result", {"tool": tool_name, "ok": ok, "duration_ms": duration_ms, "error": error}
        )


def _sdk_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    # The SDK only treats a dict as a full JSON Schema when both keys are present.
    return {"type": "object", "properties": {}, **schema}


def _describe_step(qualified: str, args: dict[str, Any]) -> str:
    return f"{qualified}({', '.join(str(value) for value in args.values())})"
