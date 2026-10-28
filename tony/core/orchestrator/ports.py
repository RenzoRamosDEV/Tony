"""What the orchestrator needs from the outside: a factory that builds a worker per task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.orchestrator.task import Task
from tony.core.runner import AgentRunner, EventSink
from tony.core.runner.cancel import CancelToken
from tony.core.subagents.ports import SubtaskHost


class TaskLog(Protocol):
    def emit(self, event_type: str, payload: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@dataclass
class Worker:
    runner: AgentRunner
    spec: AgentSpec
    catalog: ToolCatalog


class WorkerFactory(Protocol):
    def attach_host(self, host: SubtaskHost) -> None: ...

    def open_log(self, task_id: str, parent_id: str | None = None) -> TaskLog: ...

    async def build_worker(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker: ...

    async def release(self, task_id: str) -> None: ...

    async def close(self) -> None: ...
