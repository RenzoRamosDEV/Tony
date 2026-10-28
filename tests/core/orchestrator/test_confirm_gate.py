"""Orchestrator-managed confirmations (specs/tool-confirmation)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.core.orchestrator.test_orchestrator import Harness
from tony.core.mcp import ConfirmRequest
from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.task import (
    TASK_CANCELLED,
    TASK_CONFIRMED,
    TASK_NEEDS_CONFIRMATION,
    TASK_PROGRESS,
    TASK_QUEUED,
    TASK_RESULT,
    TASK_RUNNING,
    TaskStatus,
)
from tony.core.runner import TaskResult

DESTROY = [("confirm", "fake.destroy", {"path": "a"})]


@pytest.fixture
def h() -> Harness:
    return Harness()


async def start_waiting(h: Harness, script=None) -> tuple[Any, dict[str, Any]]:
    task = h.submit("a", script or DESTROY)
    await h.clock.settle()
    pending = h.factory.logs[task.id].payloads(TASK_NEEDS_CONFIRMATION)
    assert task.status == TaskStatus.WAITING_CONFIRMATION
    assert len(pending) == 1
    return task, pending[0]


async def test_approval_resumes_the_task_and_runs_the_tool_once(h: Harness) -> None:
    task, pending = await start_waiting(h)
    assert pending == {
        "confirmation_id": pending["confirmation_id"],
        "tool": "fake.destroy",
        "args": {"path": "a"},
    }

    await h.orchestrator.confirm(pending["confirmation_id"], True)
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)

    assert result.status == "ok"
    assert h.calls == ["fake.destroy"]
    assert h.factory.logs[task.id].payloads(TASK_CONFIRMED) == [
        {"confirmation_id": pending["confirmation_id"], "approved": True}
    ]
    assert [kind for kind, _ in h.orchestrator_events(task.id)] == [
        TASK_QUEUED,
        TASK_RUNNING,
        TASK_PROGRESS,
        TASK_NEEDS_CONFIRMATION,
        TASK_CONFIRMED,
        TASK_RESULT,
    ]


async def test_rejection_cancels_the_task_with_not_confirmed(h: Harness) -> None:
    task, pending = await start_waiting(h)

    await h.orchestrator.confirm(pending["confirmation_id"], False)
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)

    assert h.calls == []
    assert task.status == TaskStatus.CANCELLED
    assert result == TaskResult(
        status="cancelled",
        resumen="Tarea cancelada: el usuario no confirmó fake.destroy.",
        datos=None,
        pasos=[],
        errores=["Tool fake.destroy no confirmada por el usuario"],
    )
    assert h.orchestrator_events(task.id) == [
        (TASK_QUEUED, {"objetivo": "a", "parent_id": None}),
        (TASK_RUNNING, {}),
        (TASK_PROGRESS, {"tool": "fake.destroy", "step": 1}),
        (TASK_NEEDS_CONFIRMATION, pending),
        (TASK_CONFIRMED, {"confirmation_id": pending["confirmation_id"], "approved": False}),
        (TASK_CANCELLED, {"reason": "not_confirmed"}),
        (TASK_RESULT, {"result": result.model_dump()}),
    ]


async def test_expiry_after_confirm_timeout_counts_as_rejection(h: Harness) -> None:
    task, pending = await start_waiting(h)

    await h.clock.advance(59)
    assert task.status == TaskStatus.WAITING_CONFIRMATION

    await h.clock.advance(1)
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)
    assert h.calls == []
    assert result.status == "cancelled"
    assert h.factory.logs[task.id].payloads(TASK_CONFIRMED) == [
        {"confirmation_id": pending["confirmation_id"], "approved": False}
    ]
    assert h.factory.logs[task.id].payloads(TASK_CANCELLED) == [{"reason": "not_confirmed"}]
    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.confirm(pending["confirmation_id"], True)
    assert excinfo.value.code == "invalid_confirmation"


async def test_unknown_confirmation_id_is_invalid(h: Harness) -> None:
    task, _ = await start_waiting(h)

    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.confirm("nope", True)

    assert excinfo.value.code == "invalid_confirmation"
    assert task.status == TaskStatus.WAITING_CONFIRMATION
    assert h.calls == []


async def test_double_confirmation_is_invalid_and_does_not_rerun_the_tool(h: Harness) -> None:
    task, pending = await start_waiting(h)
    await h.orchestrator.confirm(pending["confirmation_id"], True)
    await h.orchestrator.wait(task.id)

    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.confirm(pending["confirmation_id"], True)

    assert excinfo.value.code == "invalid_confirmation"
    assert h.calls == ["fake.destroy"]


@pytest.mark.parametrize(
    "mismatch",
    [{"tool": "fake.other"}, {"args": {"path": "b"}}, {"tool": "fake.destroy", "args": {}}],
)
async def test_confirmation_for_another_tool_or_args_is_invalid(h: Harness, mismatch) -> None:
    task, pending = await start_waiting(h)

    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.confirm(pending["confirmation_id"], True, **mismatch)

    assert excinfo.value.code == "invalid_confirmation"
    assert task.status == TaskStatus.WAITING_CONFIRMATION
    assert h.factory.logs[task.id].payloads(TASK_CONFIRMED) == []


async def test_matching_tool_and_args_in_any_key_order_are_accepted(h: Harness) -> None:
    task, pending = await start_waiting(h, [("confirm", "fake.destroy", {"b": 1, "a": 2})])

    await h.orchestrator.confirm(
        pending["confirmation_id"], True, tool="fake.destroy", args={"a": 2, "b": 1}
    )

    assert (await h.orchestrator.wait(task.id)).status == "ok"


async def test_cancellation_while_waiting_invalidates_the_pending_confirmation(
    h: Harness,
) -> None:
    task, pending = await start_waiting(h)

    await h.orchestrator.cancel(task.id, "user")
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)

    assert task.status == TaskStatus.CANCELLED
    assert result.status == "cancelled"
    assert h.calls == []
    assert h.factory.logs[task.id].payloads(TASK_CONFIRMED) == []
    assert h.factory.logs[task.id].payloads(TASK_CANCELLED) == [{"reason": "user"}]
    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.confirm(pending["confirmation_id"], True)
    assert excinfo.value.code == "invalid_confirmation"
    assert task.status == TaskStatus.CANCELLED


async def test_task_timeout_with_a_pending_confirmation_ends_in_timeout() -> None:
    h = Harness(task_timeout_s=300)
    task, pending = await start_waiting(h)

    await h.clock.advance(300)
    result = await asyncio.wait_for(h.orchestrator.wait(task.id), 1)

    assert task.status == TaskStatus.TIMEOUT
    assert result.status == "timeout"
    assert h.calls == []
    with pytest.raises(OrchestratorError) as excinfo:
        await h.orchestrator.confirm(pending["confirmation_id"], True)
    assert excinfo.value.code == "invalid_confirmation"
    assert h.factory.logs[task.id].payloads(TASK_CONFIRMED) == []


class ParallelConfirmRunner:
    """Asks for two confirmations at the same time, like a model calling two tools."""

    def __init__(self, gate, task_id: str) -> None:
        self.gate = gate
        self.task_id = task_id
        self.answers: list[bool] = []

    async def run(self, spec, request, tools, events) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        first = ConfirmRequest.create(self.task_id, "fake.one", {})
        second = ConfirmRequest.create(self.task_id, "fake.two", {})
        answers = await asyncio.gather(self.gate.confirm(first), self.gate.confirm(second))
        self.answers = list(answers)
        events.emit("task.finished", {"status": "ok", "usage": {}})
        return TaskResult(status="ok", resumen="ambas")


async def test_parallel_confirmations_are_shown_one_at_a_time(h: Harness) -> None:
    runners: dict[str, ParallelConfirmRunner] = {}
    original = h.factory.build_worker

    async def build_worker(task, events, cancel_token, gate):
        worker = await original(task, events, cancel_token, gate)
        runners[task.id] = ParallelConfirmRunner(gate, task.id)
        return type(worker)(runner=runners[task.id], spec=worker.spec, catalog=worker.catalog)

    h.factory.build_worker = build_worker
    task = h.submit("a")
    await h.clock.settle()
    log = h.factory.logs[task.id]

    assert [p["tool"] for p in log.payloads(TASK_NEEDS_CONFIRMATION)] == ["fake.one"]
    await h.orchestrator.confirm(log.payloads(TASK_NEEDS_CONFIRMATION)[0]["confirmation_id"], True)
    await h.clock.settle()

    assert [p["tool"] for p in log.payloads(TASK_NEEDS_CONFIRMATION)] == ["fake.one", "fake.two"]
    assert task.status == TaskStatus.WAITING_CONFIRMATION
    await h.orchestrator.confirm(log.payloads(TASK_NEEDS_CONFIRMATION)[1]["confirmation_id"], True)

    assert (await asyncio.wait_for(h.orchestrator.wait(task.id), 1)).status == "ok"
    assert runners[task.id].answers == [True, True]
