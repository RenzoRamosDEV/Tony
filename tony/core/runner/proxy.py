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
from tony.core.runner.cancel import NOT_CONFIRMED_REASON, CancelToken
from tony.core.runner.ports import EventSink

ToolCaller = Callable[[str, dict[str, Any], float], Awaitable[ToolCallOutcome]]
Interrupt = Callable[[], Awaitable[None]]
ToolReply = dict[str, Any]
StateProvider = Callable[[], "TaskState"]

NOT_CONFIRMED = "Tool {tool} no confirmada por el usuario"
TASK_CANCELLED = "Tarea cancelada; no se ejecuta {tool}"
PROXY_VERSION = "1.0.0"


@dataclass
class TaskState:
    task_id: str
    cancel_token: CancelToken = field(default_factory=CancelToken)
    cancel_reason: str | None = None
    """Tool the user did not confirm; None when the cancellation came from outside."""
    steps: list[str] = field(default_factory=list)
    interrupt: Interrupt | None = None
    _interrupted: bool = field(default=False, repr=False)

    @property
    def cancelled(self) -> bool:
        return self.cancel_token.cancelled

    def cancel(self, tool: str) -> None:
        if self.cancel_reason is None:
            self.cancel_reason = tool
        self.cancel_token.cancel(NOT_CONFIRMED_REASON)

    async def request_interrupt(self) -> None:
        if self.interrupt is None or self._interrupted:
            return
        self._interrupted = True
        try:
            await self.interrupt()
        except Exception:  # noqa: BLE001 - interrupting is best effort
            pass


def text_reply(text: str, is_error: bool = False) -> ToolReply:
    reply: ToolReply = {"content": [{"type": "text", "text": text}]}
    if is_error:
        reply["is_error"] = True
    return reply


class ToolBarrier:
    """Transport-agnostic cancel -> allow -> confirm -> timeout -> log execution barrier.

    Builds one handler per catalog tool, each a plain `dict[str, Any] -> ToolReply`
    coroutine with no dependency on how it gets called: an in-process SDK proxy
    (`ToolProxyFactory`) and a stdio MCP gateway can both register the same handlers.
    """

    def __init__(
        self,
        catalog: ToolCatalog,
        call: ToolCaller,
        gate: ConfirmGate,
        events: EventSink,
        task_state: TaskState | StateProvider,
        tool_timeout_s: float,
        confirm_timeout_s: float,
    ) -> None:
        self._call = call
        self._gate = gate
        self._events = events
        self._current_state: StateProvider = (
            task_state if callable(task_state) else lambda: task_state
        )
        self._tool_timeout_s = tool_timeout_s
        self._confirm_timeout_s = confirm_timeout_s
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[ToolReply]]] = {
            ref.qualified: self._make_handler(ref)
            for refs in catalog.servers().values()
            for ref in refs
        }

    def handler(self, qualified: str) -> Callable[[dict[str, Any]], Awaitable[ToolReply]]:
        return self._handlers[qualified]

    @property
    def _state(self) -> TaskState:
        return self._current_state()

    def _make_handler(self, ref: ToolRef) -> Callable[[dict[str, Any]], Awaitable[ToolReply]]:
        async def handler(args: dict[str, Any]) -> ToolReply:
            return await self._execute(ref, args)

        return handler

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


class ToolProxyFactory:
    """In-process SDK adapter: wraps a `ToolBarrier` with `claude_agent_sdk` tool wiring."""

    def __init__(
        self,
        catalog: ToolCatalog,
        call: ToolCaller,
        gate: ConfirmGate,
        events: EventSink,
        task_state: TaskState | StateProvider,
        tool_timeout_s: float,
        confirm_timeout_s: float,
    ) -> None:
        self.barrier = ToolBarrier(
            catalog, call, gate, events, task_state, tool_timeout_s, confirm_timeout_s
        )
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
        return self.barrier.handler(qualified)

    def _make_tool(self, ref: ToolRef) -> SdkMcpTool:
        annotations = ToolAnnotations(destructiveHint=True) if ref.destructive else None
        schema = _sdk_input_schema(ref.input_schema)
        return tool(ref.name, ref.description, schema, annotations=annotations)(
            self.barrier.handler(ref.qualified)
        )


def _sdk_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    # The SDK only treats a dict as a full JSON Schema when both keys are present.
    return {"type": "object", "properties": {}, **schema}


def _describe_step(qualified: str, args: dict[str, Any]) -> str:
    return f"{qualified}({', '.join(str(value) for value in args.values())})"
