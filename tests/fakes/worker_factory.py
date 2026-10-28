"""WorkerFactory double: one ScriptedRunner per task, scripts keyed by `objetivo`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.fakes.clock import FakeClock
from tests.fakes.scripted_runner import ScriptedRunner, Step
from tests.fakes.sinks import ListEventSink
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.orchestrator.ports import Worker
from tony.core.orchestrator.task import Task
from tony.core.runner import AgentRunner, EventSink
from tony.core.runner.cancel import CancelToken
from tony.core.runner.proxy import ToolCaller

WORKER_SPEC = AgentSpec(name="viernes", role="worker", model="claude-sonnet", path=Path("/tmp/v"))


class FakeWorkerFactory:
    def __init__(self, clock: FakeClock, call: ToolCaller | None = None) -> None:
        self.clock = clock
        self.call = call
        self.scripts: dict[str, list[Step]] = {}
        self.runners: dict[str, AgentRunner] = {}
        self.custom_runners: dict[str, AgentRunner] = {}
        self.logs: dict[str, ListEventSink] = {}
        self.built: list[str] = []
        self.closed = False

    def open_log(self, task_id: str) -> ListEventSink:
        self.logs[task_id] = ListEventSink()
        return self.logs[task_id]

    async def build_worker(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        self.built.append(task.id)
        runner: Any = self.custom_runners.get(task.request.objetivo)
        if runner is None:
            runner = ScriptedRunner(
                task.id,
                self.scripts.get(task.request.objetivo, []),
                cancel_token=cancel_token,
                clock=self.clock,
                call=self.call,
                gate=gate,
            )
        self.runners[task.id] = runner
        return Worker(runner=runner, spec=WORKER_SPEC, catalog=ToolCatalog.empty())

    async def close(self) -> None:
        self.closed = True
