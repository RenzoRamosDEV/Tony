"""WorkerFactory double: one ScriptedRunner per task, scripts keyed by `objetivo`.

`runner_builders` lets a test build a custom runner that knows its Task (e.g. to submit
subtasks); `custom_runners` takes a ready-made runner.
"""

from __future__ import annotations

from collections.abc import Callable
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
        self.runner_builders: dict[
            str, Callable[[Task, CancelToken, ConfirmGate], AgentRunner]
        ] = {}
        self.logs: dict[str, ListEventSink] = {}
        self.parents: dict[str, str] = {}
        self.built: list[str] = []
        self.released: list[str] = []
        self.host: Any = None
        self.closed = False

    def attach_host(self, host: Any) -> None:
        self.host = host

    def open_log(self, task_id: str, parent_id: str | None = None) -> ListEventSink:
        self.logs[task_id] = ListEventSink()
        if parent_id is not None:
            self.parents[task_id] = parent_id
        return self.logs[task_id]

    async def build_worker(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        self.built.append(task.id)
        runner: Any = self.custom_runners.get(task.request.objetivo)
        builder = self.runner_builders.get(task.request.objetivo)
        if runner is None and builder is not None:
            runner = builder(task, cancel_token, gate)
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

    async def release(self, task_id: str) -> None:
        self.released.append(task_id)

    async def close(self) -> None:
        self.closed = True
