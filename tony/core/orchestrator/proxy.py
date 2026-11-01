from typing import Any, Protocol

from tony.core.config.placeholders import SecretMasker
from tony.core.events import log_events
from tony.core.events.messages import ToolCall
from tony.core.guard.port import Guard
from tony.core.mcp.manager import CatalogTool
from tony.core.orchestrator.ports import EventSink, ProxiedTool, ToolReply


class ToolCaller(Protocol):
    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply: ...


class ToolProxy:
    """The single path every agent tool call takes: log, guard, execute, mask, log."""

    def __init__(
        self,
        *,
        task_id: str,
        agent: str,
        guard: Guard,
        caller: ToolCaller,
        sink: EventSink,
        masker: SecretMasker,
    ) -> None:
        self._task_id = task_id
        self._agent = agent
        self._guard = guard
        self._caller = caller
        self._sink = sink
        self._masker = masker

    def wrap(self, catalog: list[CatalogTool]) -> list[ProxiedTool]:
        return [
            ProxiedTool(
                id=tool.id,
                description=tool.description,
                input_schema=tool.input_schema,
                handler=self._handler_for(tool.id),
            )
            for tool in catalog
        ]

    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        self._sink.emit(log_events.tool_call(tool_id, args))
        reply = await self._execute(tool_id, args)
        self._sink.emit(log_events.tool_result(tool_id, ok=not reply.is_error, content=reply.text))
        return reply

    async def _execute(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        envelope = ToolCall(task_id=self._task_id, agent=self._agent, tool=tool_id, args=args)
        decision = await self._guard.decide(envelope)
        if decision != "allow":
            return ToolReply(
                text=f"tool {tool_id} was not executed: guard decision '{decision}'",
                is_error=True,
            )
        return await self._caller.call(tool_id, args)

    def _handler_for(self, tool_id: str):
        async def handler(args: dict[str, Any]) -> ToolReply:
            return await self.call(tool_id, args)

        return handler
