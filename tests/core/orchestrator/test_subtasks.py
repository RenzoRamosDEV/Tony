"""Subtasks: shared deadline, cascade, mirrored confirmation and events (specs/subagents)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.worker_factory import FakeWorkerFactory
from tony.core.config import Limits
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ConfirmRequest, ToolCallOutcome
from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.orchestrator import Orchestrator
from tony.core.orchestrator.task import (
    SUBTASK_FINISHED,
    SUBTASK_STARTED,
    TASK_CANCELLED,
    TASK_NEEDS_CONFIRMATION,
    Event,
    Task,
    TaskStatus,
)
from tony.core.runner import EventSink, TaskRequest, TaskResult
from tony.core.runner.cancel import CancelToken

OK = TaskResult(status="ok", resumen="hecho")
CHILD = "investigador"


class ParentRunner:
    """Runner of the root task: optionally waits, then launches `children` and waits for them."""

    def __init__(
        self,
        h: Harness,
        task: Task,
        gate: ConfirmGate,
        children: list[str],
        before_s: float = 0,
        after_s: float = 0,
        own_confirm: str | None = None,
    ) -> None:
        self.h = h
        self.task = task
        self.gate = gate
        self.children = children
        self.before_s = before_s
        self.after_s = after_s
        self.own_confirm = own_confirm
        self.results: list[TaskResult] = []

    async def run(self, spec, request, tools, events: EventSink) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        await self.h.clock.sleep(self.before_s)
        own = None
        if self.own_confirm is not None:
            own = asyncio.ensure_future(
                self.gate.confirm(ConfirmRequest.create(self.task.id, self.own_confirm, {}))
            )
        launched = [
            self.h.orchestrator.submit_subtask(self.task.id, CHILD, TaskRequest(objetivo=name))
            for name in self.children
        ]
        self.results = [await self.h.orchestrator.wait(t.id) for t in launched]
        if own is not None:
            await own
        await self.h.clock.sleep(self.after_s)
        events.emit("task.finished", {"status": "ok", "usage": {}})
        return self.results[0] if len(self.results) == 1 else OK


class Harness:
    def __init__(self, task_timeout_s: float = 10) -> None:
        self.clock = FakeClock()
        self.calls: list[str] = []
        self.factory = FakeWorkerFactory(self.clock, call=self.call)
        self.orchestrator = Orchestrator(
            self.factory, Limits(task_timeout_s=task_timeout_s, confirm_timeout_s=60), self.clock
        )
        self.streams: dict[str, asyncio.Task[list[Event]]] = {}

    async def call(self, qualified: str, args: dict[str, Any], timeout: float) -> ToolCallOutcome:
        self.calls.append(qualified)
        return ToolCallOutcome(ok=True, content="", duration_ms=1)

    def parent(self, objetivo: str, children: list[str], **options: Any) -> Task:
        self.factory.runner_builders[objetivo] = lambda task, token, gate: ParentRunner(
            self, task, gate, children, **options
        )
        task = self.orchestrator.submit(TaskRequest(objetivo=objetivo))
        self.streams[task.id] = asyncio.ensure_future(self.collect(task.id))
        return task

    async def collect(self, task_id: str) -> list[Event]:
        return [event async for event in self.orchestrator.events(task_id)]

    async def events(self, task_id: str) -> list[Event]:
        return await asyncio.wait_for(self.streams[task_id], 1)

    def child(self, parent: Task, index: int = 0) -> Task:
        return self.orchestrator.children(parent.id)[index]

    def log(self, task_id: str, kind: str) -> list[dict[str, Any]]:
        return self.factory.logs[task_id].payloads(kind)


@pytest.fixture
def h() -> Harness:
    return Harness()


def test_attach_host_receives_the_orchestrator(h: Harness) -> None:
    assert h.factory.host is h.orchestrator


async def test_subtask_runs_as_a_child_with_its_agent_and_events(h: Harness) -> None:
    h.factory.scripts["c1"] = [("tool", "fake.echo", {"t": 1})]
    parent = h.parent("p", ["c1"])
    await h.clock.settle()

    result = await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)
    child = h.child(parent)

    assert child.agent == CHILD and child.parent_id == parent.id and parent.agent is None
    assert child.status == TaskStatus.DONE and result.status == "ok"
    assert h.orchestrator.children(parent.id) == [child]
    assert h.orchestrator.children(child.id) == []
    parent_events = [(e.type, e.payload) for e in await h.events(parent.id)]
    assert (SUBTASK_STARTED, {"task_id": child.id, "agent": CHILD}) in parent_events
    assert (SUBTASK_FINISHED, {"task_id": child.id, "status": "done"}) in parent_events
    assert h.factory.parents[child.id] == parent.id
    assert h.log(child.id, "task.queued") == [{"objetivo": "c1", "parent_id": parent.id}]
    assert h.factory.released == [child.id, parent.id]
    assert isinstance(h.factory.runners[child.id].calls[0][0], AgentSpec)


async def test_subtask_of_an_unknown_or_finished_parent_is_rejected(h: Harness) -> None:
    with pytest.raises(OrchestratorError) as info:
        h.orchestrator.submit_subtask("nadie", CHILD, TaskRequest(objetivo="x"))
    assert info.value.code == "unknown_task"

    done = h.orchestrator.submit(TaskRequest(objetivo="done"))
    await asyncio.wait_for(h.orchestrator.wait(done.id), 1)
    with pytest.raises(OrchestratorError):
        h.orchestrator.submit_subtask(done.id, CHILD, TaskRequest(objetivo="x"))


async def test_child_inherits_the_remaining_time_of_its_parent(h: Harness) -> None:
    h.factory.scripts["c1"] = [("sleep", 5)]
    parent = h.parent("p", ["c1"], before_s=8)
    await h.clock.advance(8)
    child = h.child(parent)
    assert child.status == TaskStatus.RUNNING

    await h.clock.advance(2)

    assert child.status == TaskStatus.TIMEOUT
    assert parent.status == TaskStatus.TIMEOUT
    result = await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)
    assert result.status == "timeout"
    assert h.factory.runners[parent.id].results[0].status == "timeout"


async def test_cancelling_the_parent_cascades_to_its_running_child(h: Harness) -> None:
    h.factory.scripts["c1"] = [("sleep", 5), ("tool", "fake.echo", {})]
    parent = h.parent("p", ["c1"])
    await h.clock.settle()
    child = h.child(parent)

    await h.orchestrator.cancel(parent.id, "user")
    await h.clock.settle()

    assert child.status == TaskStatus.CANCELLED
    assert parent.status == TaskStatus.CANCELLED
    assert h.log(child.id, TASK_CANCELLED) == [{"reason": "user"}]
    assert h.calls == []
    assert (await asyncio.wait_for(h.orchestrator.wait(child.id), 1)).status == "cancelled"
    assert h.factory.runners[child.id].interrupted_by == "user"


async def test_parent_timeout_expires_its_child(h: Harness) -> None:
    h.factory.scripts["c1"] = [("sleep", 20)]
    parent = h.parent("p", ["c1"])
    await h.clock.settle()
    child = h.child(parent)

    await h.clock.advance(10)

    assert (parent.status, child.status) == (TaskStatus.TIMEOUT, TaskStatus.TIMEOUT)
    assert h.factory.runners[child.id].interrupted_by == "timeout"


async def test_child_confirmation_is_mirrored_in_the_parent_stream(h: Harness) -> None:
    h.factory.scripts["c1"] = [("confirm", "fs.write_file", {"path": "x"})]
    parent = h.parent("p", ["c1"], after_s=5)
    await h.clock.settle()
    child = h.child(parent)

    assert child.status == TaskStatus.WAITING_CONFIRMATION
    assert parent.status == TaskStatus.RUNNING
    pending = h.log(child.id, TASK_NEEDS_CONFIRMATION)[0]
    await h.orchestrator.confirm(pending["confirmation_id"], False)
    await h.clock.settle()

    assert child.status == TaskStatus.CANCELLED
    assert parent.status == TaskStatus.RUNNING
    assert h.log(child.id, TASK_CANCELLED) == [{"reason": "not_confirmed"}]
    child_result = h.factory.runners[parent.id].results[0]
    assert child_result.status == "cancelled"
    await h.clock.advance(5)
    mirrored = [e.payload for e in await h.events(parent.id) if e.type == TASK_NEEDS_CONFIRMATION]
    assert mirrored == [
        {
            "confirmation_id": pending["confirmation_id"],
            "tool": "fs.write_file",
            "args": {"path": "x"},
            "task_id": child.id,
        }
    ]
    assert h.log(parent.id, TASK_NEEDS_CONFIRMATION) == []


async def test_approved_child_confirmation_lets_the_child_continue(h: Harness) -> None:
    h.factory.scripts["c1"] = [("confirm", "fs.write_file", {})]
    parent = h.parent("p", ["c1"])
    await h.clock.settle()
    child = h.child(parent)
    pending = h.log(child.id, TASK_NEEDS_CONFIRMATION)[0]

    await h.orchestrator.confirm(pending["confirmation_id"], True, "fs.write_file", {})

    assert (await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)).status == "ok"
    assert child.status == TaskStatus.DONE
    assert h.calls == ["fs.write_file"]


async def test_parent_and_child_confirmations_are_serialised_by_the_root(h: Harness) -> None:
    h.factory.scripts["c1"] = [("confirm", "fs.write_file", {})]
    parent = h.parent("p", ["c1"], own_confirm="fs.move_file")
    await h.clock.settle()
    child = h.child(parent)

    assert parent.status == TaskStatus.WAITING_CONFIRMATION
    assert child.status == TaskStatus.RUNNING
    assert h.log(child.id, TASK_NEEDS_CONFIRMATION) == []
    first = h.log(parent.id, TASK_NEEDS_CONFIRMATION)[0]
    await h.orchestrator.confirm(first["confirmation_id"], True)
    await h.clock.settle()

    assert child.status == TaskStatus.WAITING_CONFIRMATION
    second = h.log(child.id, TASK_NEEDS_CONFIRMATION)[0]
    await h.orchestrator.confirm(second["confirmation_id"], True)
    assert (await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)).status == "ok"


async def test_two_children_run_in_parallel_and_are_listed_with_their_states(h: Harness) -> None:
    h.factory.scripts["c1"] = [("sleep", 3)]
    h.factory.scripts["c2"] = [("sleep", 1)]
    parent = h.parent("p", ["c1", "c2"])
    await h.clock.settle()

    await h.clock.advance(1)

    statuses = {c.request.objetivo: c.status for c in h.orchestrator.children(parent.id)}
    assert statuses == {"c1": TaskStatus.RUNNING, "c2": TaskStatus.DONE}
    await h.clock.advance(2)
    assert (await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)).status == "ok"


async def test_close_cancels_children_and_releases_everything(h: Harness) -> None:
    h.factory.scripts["c1"] = [("sleep", 50)]
    parent = h.parent("p", ["c1"])
    await h.clock.settle()
    child = h.child(parent)

    await asyncio.wait_for(h.orchestrator.close(), 1)

    assert child.status == TaskStatus.CANCELLED and parent.status == TaskStatus.CANCELLED
    assert set(h.factory.released) == {child.id, parent.id}
    assert h.factory.closed is True


async def test_child_task_events_name_their_parent(h: Harness) -> None:
    h.factory.scripts["c1"] = []
    parent = h.parent("p", ["c1"])
    await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)
    child = h.child(parent)

    child_events = (
        await h.events(child.id)
        if child.id in h.streams
        else [e async for e in h.orchestrator.events(child.id)]
    )

    assert {e.parent_id for e in child_events} == {parent.id}
    assert {e.task_id for e in child_events} == {child.id}
    assert {e.parent_id for e in await h.events(parent.id)} == {None}


async def test_cancel_token_of_the_child_is_distinct_from_the_parent(h: Harness) -> None:
    h.factory.scripts["c1"] = [("sleep", 2)]
    parent = h.parent("p", ["c1"], after_s=3)
    await h.clock.settle()
    child = h.child(parent)

    await h.orchestrator.cancel(child.id, "user")
    await h.clock.settle()

    assert child.status == TaskStatus.CANCELLED
    assert parent.status == TaskStatus.RUNNING
    assert isinstance(h.factory.runners[child.id].cancel_token, CancelToken)
    await h.clock.advance(3)
    assert parent.status == TaskStatus.CANCELLED
    assert h.factory.runners[parent.id].results[0].status == "cancelled"


# --- children cancelled before they start, and release failures (review of change 03) ---------


async def test_child_cancelled_in_cascade_before_starting_still_gets_a_result(h: Harness) -> None:
    results: list[TaskResult] = []

    class CancellingParent:
        def __init__(self, task: Task) -> None:
            self.task = task

        async def run(self, spec, request, tools, events: EventSink) -> TaskResult:
            child = h.orchestrator.submit_subtask(self.task.id, CHILD, TaskRequest(objetivo="c1"))
            await h.orchestrator.cancel(self.task.id, "user")
            results.append(await asyncio.wait_for(h.orchestrator.wait(child.id), 1))
            return OK

    h.factory.runner_builders["p"] = lambda task, token, gate: CancellingParent(task)
    parent = h.orchestrator.submit(TaskRequest(objetivo="p"))
    stream = asyncio.ensure_future(h.collect(parent.id))
    await h.clock.settle()
    child = h.child(parent)

    assert results and results[0].status == "cancelled"
    assert child.status == TaskStatus.CANCELLED and child.finished.is_set()
    assert child.result is not None and child.result.status == "cancelled"
    assert h.log(child.id, "task.result") == [{"result": child.result.model_dump()}]
    assert child.id not in h.factory.built
    parent_events = [(e.type, e.payload) for e in await asyncio.wait_for(stream, 1)]
    assert (SUBTASK_FINISHED, {"task_id": child.id, "status": "cancelled"}) in parent_events


async def test_release_failure_is_logged_and_never_blocks_finishing(h: Harness, caplog) -> None:
    async def failing_release(task_id: str) -> None:
        h.factory.released.append(task_id)
        raise RuntimeError("stop roto")

    h.factory.release = failing_release  # type: ignore[method-assign]
    parent = h.parent("p", ["c1"])
    following = h.orchestrator.submit(TaskRequest(objetivo="siguiente"))

    with caplog.at_level("WARNING"):
        result = await asyncio.wait_for(h.orchestrator.wait(parent.id), 1)
        await asyncio.wait_for(h.orchestrator.wait(following.id), 1)

    child = h.child(parent)
    assert result.status == "ok" and child.finished.is_set() and parent.finished.is_set()
    assert following.status == TaskStatus.DONE
    assert h.factory.released == [child.id, parent.id, following.id]
    assert any("stop roto" in r.message and child.id in r.message for r in caplog.records)
