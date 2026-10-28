"""Orchestrator lifecycle (specs/task-orchestrator) with ScriptedRunner and FakeClock."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.worker_factory import FakeWorkerFactory
from tony.core.config import Limits
from tony.core.mcp import ToolCallOutcome
from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.orchestrator import CLEANUP_BUDGET_S, Orchestrator
from tony.core.orchestrator.task import (
    TASK_CANCELLED,
    TASK_PROGRESS,
    TASK_QUEUED,
    TASK_RESULT,
    TASK_RUNNING,
    Event,
    TaskStatus,
)
from tony.core.runner import TaskRequest, TaskResult

OK = TaskResult(status="ok", resumen="hecho")


class Harness:
    def __init__(self, task_timeout_s: float = 300) -> None:
        self.clock = FakeClock()
        self.calls: list[str] = []
        self.factory = FakeWorkerFactory(self.clock, call=self.slow_call)
        limits = Limits(task_timeout_s=task_timeout_s, confirm_timeout_s=60)
        self.orchestrator = Orchestrator(self.factory, limits, clock=self.clock)

    async def slow_call(self, qualified: str, args: dict[str, Any], timeout: float):
        self.calls.append(qualified)
        if qualified.endswith("slow"):
            await self.clock.sleep(2)
        return ToolCallOutcome(ok=True, content="", duration_ms=1)

    def submit(self, objetivo: str, script: list | None = None, parent_id: str | None = None):
        if script is not None:
            self.factory.scripts[objetivo] = script
        return self.orchestrator.submit(TaskRequest(objetivo=objetivo), parent_id=parent_id)

    def orchestrator_events(self, task_id: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (kind, payload)
            for kind, payload in self.factory.logs[task_id].events
            if kind.startswith("task.") and kind not in ("task.started", "task.finished")
        ]


@pytest.fixture
def h() -> Harness:
    return Harness()


async def test_submit_returns_a_queued_task_that_starts_and_completes(h: Harness) -> None:
    task = h.submit("a", [("tool", "fake.echo", {"text": "x"})])

    assert task.status == TaskStatus.QUEUED
    assert task.id
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)

    assert result.status == "ok"
    assert task.status == TaskStatus.DONE
    assert task.result == result
    assert task.created_at == 0 and task.started_at == 0 and task.finished_at == 0
    assert h.orchestrator_events(task.id) == [
        (TASK_QUEUED, {"objetivo": "a", "parent_id": None}),
        (TASK_RUNNING, {}),
        (TASK_PROGRESS, {"tool": "fake.echo", "step": 1}),
        (TASK_RESULT, {"result": result.model_dump()}),
    ]
    assert h.factory.logs[task.id].types()[-1] == TASK_RESULT
    assert h.factory.logs[task.id].closed is True


async def test_one_root_runs_at_a_time_in_fifo_order(h: Harness) -> None:
    t1 = h.submit("t1", [("sleep", 5)])
    t2 = h.submit("t2", [("sleep", 5)])
    t3 = h.submit("t3", [])
    await h.clock.settle()

    assert (t1.status, t2.status, t3.status) == (
        TaskStatus.RUNNING,
        TaskStatus.QUEUED,
        TaskStatus.QUEUED,
    )

    await h.clock.advance(5)
    assert (t1.status, t2.status, t3.status) == (
        TaskStatus.DONE,
        TaskStatus.RUNNING,
        TaskStatus.QUEUED,
    )

    await h.clock.advance(5)
    assert (t2.status, t3.status) == (TaskStatus.DONE, TaskStatus.DONE)
    assert h.factory.built == [t1.id, t2.id, t3.id]


async def test_eleventh_queued_task_is_rejected(h: Harness) -> None:
    h.submit("active", [("sleep", 5)])
    await h.clock.settle()
    for i in range(10):
        h.submit(f"q{i}")

    with pytest.raises(OrchestratorError) as excinfo:
        h.submit("q10")

    assert excinfo.value.code == "queue_full"
    assert len(h.orchestrator.tasks) == 11


async def test_unknown_parent_is_rejected_without_creating_the_task(h: Harness) -> None:
    with pytest.raises(OrchestratorError) as excinfo:
        h.submit("child", parent_id="nope")

    assert excinfo.value.code == "unknown_task"
    assert h.orchestrator.tasks == {}


async def test_subtask_runs_without_waiting_for_the_root(h: Harness) -> None:
    root = h.submit("root", [("sleep", 5)])
    await h.clock.settle()

    child = h.submit("child", [], parent_id=root.id)
    await h.clock.settle()

    assert child.parent_id == root.id
    assert child.status == TaskStatus.DONE
    assert root.status == TaskStatus.RUNNING
    assert h.orchestrator_events(child.id)[0] == (
        TASK_QUEUED,
        {"objetivo": "child", "parent_id": root.id},
    )


async def test_subtask_of_a_finished_parent_is_rejected(h: Harness) -> None:
    root = h.submit("root", [])
    await h.orchestrator.wait(root.id)

    with pytest.raises(OrchestratorError) as excinfo:
        h.submit("child", parent_id=root.id)

    assert excinfo.value.code == "unknown_task"


async def test_wait_returns_immediately_for_a_finished_task_and_fails_for_unknown(
    h: Harness,
) -> None:
    task = h.submit("a", [])
    await h.orchestrator.wait(task.id)

    assert await asyncio.wait_for(h.orchestrator.wait(task.id), 0.1) == task.result
    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.wait("missing")
    assert excinfo.value.code == "unknown_task"


async def test_runner_exception_fails_the_task_with_the_message(h: Harness) -> None:
    task = h.submit("a", [("raise", "boom")])

    result = await h.orchestrator.wait(task.id)

    assert task.status == TaskStatus.FAILED
    assert result.status == "error"
    assert result.errores == ["boom"]
    assert result.resumen == "Error del motor de ejecución: boom"
    assert h.orchestrator_events(task.id)[-1][0] == TASK_RESULT


class IgnoringRunner:
    """Returns OK after a clock sleep no matter what the token says."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock

    async def run(self, spec, request, tools, events) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        await self.clock.sleep(2)
        events.emit("task.finished", {"status": "ok", "usage": {}})
        return OK


async def test_late_ok_result_is_ignored_after_cancellation(h: Harness) -> None:
    h.factory.custom_runners["a"] = IgnoringRunner(h.clock)
    task = h.submit("a")
    await h.clock.settle()

    await h.orchestrator.cancel(task.id, "user")
    await h.clock.advance(2)

    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)
    assert task.status == TaskStatus.CANCELLED
    assert result.status == "cancelled"
    assert result.errores == ["cancelada por el usuario"]


async def test_cancelling_a_queued_task_removes_it_from_the_queue(h: Harness) -> None:
    t1 = h.submit("t1", [("sleep", 5)])
    t2 = h.submit("t2", [])
    t3 = h.submit("t3", [])
    await h.clock.settle()

    await h.orchestrator.cancel(t2.id)

    assert t2.status == TaskStatus.CANCELLED
    result = await asyncio.wait_for(h.orchestrator.wait(t2.id), 1)
    assert result.status == "cancelled"
    assert h.orchestrator_events(t2.id) == [
        (TASK_QUEUED, {"objetivo": "t2", "parent_id": None}),
        (TASK_CANCELLED, {"reason": "user"}),
        (TASK_RESULT, {"result": result.model_dump()}),
    ]
    await h.clock.advance(5)
    assert t1.status == TaskStatus.DONE
    assert t3.status == TaskStatus.DONE
    assert t2.id not in h.factory.built


async def test_cancel_during_a_long_tool_returns_at_once_and_blocks_the_next_tool(
    h: Harness,
) -> None:
    task = h.submit("a", [("tool", "fake.slow", {}), ("tool", "fake.next", {})])
    await h.clock.settle()
    assert h.calls == ["fake.slow"]

    await asyncio.wait_for(h.orchestrator.cancel(task.id, "user"), 0.1)

    assert task.status == TaskStatus.CANCELLED
    assert not task.finished.is_set()
    await h.clock.advance(2)
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)
    assert h.calls == ["fake.slow"]
    assert result.status == "cancelled"
    assert (TASK_CANCELLED, {"reason": "user"}) in h.orchestrator_events(task.id)
    assert h.orchestrator_events(task.id)[-1][0] == TASK_RESULT


async def test_cancelling_a_finished_task_changes_nothing(h: Harness) -> None:
    task = h.submit("a", [])
    await h.orchestrator.wait(task.id)
    before = list(h.factory.logs[task.id].events)

    await h.orchestrator.cancel(task.id)

    assert task.status == TaskStatus.DONE
    assert h.factory.logs[task.id].events == before


async def test_cancelling_an_unknown_task_fails(h: Harness) -> None:
    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.cancel("missing")

    assert excinfo.value.code == "unknown_task"


async def test_task_timeout_interrupts_the_runner_and_ends_in_timeout() -> None:
    h = Harness(task_timeout_s=300)
    task = h.submit("a", [("sleep", 1000)])
    await h.clock.settle()

    await h.clock.advance(299)
    assert task.status == TaskStatus.RUNNING

    await h.clock.advance(1)
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)
    assert task.status == TaskStatus.TIMEOUT
    assert task.finished_at == 300
    assert result.status == "timeout"
    assert result.errores == ["timeout de tarea tras 300 s"]
    assert h.factory.runners[task.id].interrupted_by == "timeout"


async def test_events_replays_history_and_ends_after_result(h: Harness) -> None:
    task = h.submit("a", [("tool", "fake.echo", {})])
    await h.orchestrator.wait(task.id)

    events: list[Event] = [event async for event in h.orchestrator.events(task.id)]

    assert [e.type for e in events if e.type.startswith("task.")] == [
        TASK_QUEUED,
        TASK_RUNNING,
        "task.started",
        TASK_PROGRESS,
        "task.finished",
        TASK_RESULT,
    ]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


async def test_events_of_an_unknown_task_fails(h: Harness) -> None:
    with pytest.raises(OrchestratorError) as excinfo:
        h.orchestrator.events("missing")

    assert excinfo.value.code == "unknown_task"


async def test_close_cancels_active_tasks_and_closes_the_factory(h: Harness) -> None:
    task = h.submit("a", [("sleep", 1000)])
    await h.clock.settle()

    await asyncio.wait_for(h.orchestrator.close(), 1)

    assert h.factory.closed is True
    assert task.status == TaskStatus.CANCELLED
    assert task.finished.is_set()


class StuckRunner:
    """Ignores the cancel token and never returns."""

    async def run(self, spec, request, tools, events) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_deadline_publishes_timeout_and_frees_the_queue_even_if_the_runner_never_ends(
    h: Harness,
) -> None:
    h.factory.custom_runners["stuck"] = StuckRunner()
    stuck = h.submit("stuck")
    following = h.submit("next", [])
    await h.clock.settle()

    await h.clock.advance(300)
    assert stuck.status == TaskStatus.TIMEOUT
    await h.clock.advance(CLEANUP_BUDGET_S)

    result = await asyncio.wait_for(h.orchestrator.wait(stuck.id), 1)
    assert result.status == "timeout"
    assert stuck.finished.is_set()
    assert h.orchestrator_events(stuck.id)[-1][0] == TASK_RESULT
    assert following.status == TaskStatus.DONE
    await asyncio.wait_for(h.orchestrator.close(), 1)


async def test_deadline_counts_from_running_and_covers_the_worker_build(h: Harness) -> None:
    async def never_build(task, events, cancel_token, gate):
        await asyncio.Event().wait()

    h.factory.build_worker = never_build  # type: ignore[method-assign]
    task = h.submit("a")
    await h.clock.settle()
    assert task.started_at == 0

    await h.clock.advance(300)
    assert task.status == TaskStatus.TIMEOUT
    await h.clock.advance(CLEANUP_BUDGET_S)

    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)
    assert result.status == "timeout"
    assert task.finished_at == 300 + CLEANUP_BUDGET_S


async def test_cancelled_task_whose_runner_never_returns_settles_after_the_budget(
    h: Harness,
) -> None:
    h.factory.custom_runners["stuck"] = StuckRunner()
    task = h.submit("stuck")
    await h.clock.settle()

    await h.orchestrator.cancel(task.id, "user")
    assert not task.finished.is_set()
    await h.clock.advance(CLEANUP_BUDGET_S)

    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)
    assert result.status == "cancelled"
