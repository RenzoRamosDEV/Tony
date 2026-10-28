"""Ports implemented by adapters (SDK runner, JSONL sink) and by test doubles."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner.contracts import TaskRequest, TaskResult


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event_type: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class AgentRunner(Protocol):
    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult: ...
