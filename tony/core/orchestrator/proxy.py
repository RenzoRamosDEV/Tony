import asyncio
import json
from typing import Any, Protocol

from tony.core.config.placeholders import SecretMasker
from tony.core.events import log_events
from tony.core.events.messages import Ruling, ToolCall
from tony.core.guard.port import Guard
from tony.core.mcp.manager import CatalogTool
from tony.core.orchestrator.ports import EventSink, ProxiedTool, ToolReply
from tony.core.orchestrator.supervisor import TaskSupervisor


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
        supervisor: TaskSupervisor,
    ) -> None:
        self._task_id = task_id
        self._agent = agent
        self._guard = guard
        self._caller = caller
        self._sink = sink
        self._masker = masker
        self._supervisor = supervisor

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
        reply = await self._judge_and_execute(tool_id, args)
        reply = ToolReply(text=self._masker.mask(reply.text), is_error=reply.is_error)
        self._sink.emit(log_events.tool_result(tool_id, ok=not reply.is_error, content=reply.text))
        return reply

    async def _judge_and_execute(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        if not self._supervisor.step(self._agent):
            return _not_executed(tool_id, self._supervisor.reason or "task cancelled")
        envelope = ToolCall(task_id=self._task_id, agent=self._agent, tool=tool_id, args=args)
        ruling = await self._guard.decide(envelope)
        if ruling.verdict == "deny":
            self._supervisor.denied(tool_id, ruling.rule)
            return _blocked(ruling)
        if ruling.verdict == "confirm" and ruling.user_decision != "allow":
            self._supervisor.unconfirmed(tool_id, ruling.rule, ruling.user_decision)
            decision = ruling.user_decision or "deny"
            return _not_executed(tool_id, f"not confirmed by the user ({decision})")
        return await self._execute(tool_id, args)

    async def _execute(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        timeout = self._supervisor.limits.tool_timeout_s
        try:
            return await asyncio.wait_for(self._caller.call(tool_id, args), timeout)
        except TimeoutError:
            return ToolReply(text=f"tool {tool_id} timed out after {timeout:g} s", is_error=True)
        except Exception as error:
            return ToolReply(text=f"tool {tool_id} failed: {error}", is_error=True)

    def _handler_for(self, tool_id: str):
        async def handler(args: dict[str, Any]) -> ToolReply:
            return await self.call(tool_id, args)

        return handler


def _blocked(ruling: Ruling) -> ToolReply:
    text = json.dumps({"error": "blocked_by_policy", "rule": ruling.rule})
    return ToolReply(text=text, is_error=True)


def _not_executed(tool_id: str, why: str) -> ToolReply:
    return ToolReply(text=f"tool {tool_id} was not executed: {why}", is_error=True)
