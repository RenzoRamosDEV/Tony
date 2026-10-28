"""AgentRunner double returning a preconfigured TaskResult."""

from __future__ import annotations

from typing import Any

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import EventSink, TaskRequest, TaskResult

DEFAULT_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.01, "num_turns": 2}


class FakeAgentRunner:
    def __init__(
        self,
        result: TaskResult,
        events: list[tuple[str, dict[str, Any]]] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.result = result
        self.scripted_events = events or []
        self.usage = usage if usage is not None else DEFAULT_USAGE
        self.calls: list[tuple[AgentSpec, TaskRequest, ToolCatalog]] = []

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        self.calls.append((spec, request, tools))
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        for event_type, payload in self.scripted_events:
            events.emit(event_type, payload)
        events.emit("task.finished", {"status": self.result.status, "usage": self.usage})
        return self.result
