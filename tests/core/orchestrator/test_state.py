"""Task state machine (specs/task-orchestrator "Máquina de estados")."""

from __future__ import annotations

import pytest

from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.state import TRANSITIONS, transition
from tony.core.orchestrator.task import FINAL_STATUSES, Task, TaskStatus, status_for_result
from tony.core.runner import TaskRequest, TaskResult


def task(status: TaskStatus = TaskStatus.QUEUED) -> Task:
    return Task(id="t1", request=TaskRequest(objetivo="o"), status=status)


def test_running_task_can_wait_for_confirmation_and_resume() -> None:
    t = task(TaskStatus.RUNNING)

    transition(t, TaskStatus.WAITING_CONFIRMATION)
    assert t.status == TaskStatus.WAITING_CONFIRMATION

    transition(t, TaskStatus.RUNNING)
    assert t.status == TaskStatus.RUNNING


def test_queued_task_cannot_wait_for_confirmation() -> None:
    t = task(TaskStatus.QUEUED)

    with pytest.raises(OrchestratorError) as excinfo:
        transition(t, TaskStatus.WAITING_CONFIRMATION)

    assert excinfo.value.code == "invalid_transition"
    assert t.status == TaskStatus.QUEUED


@pytest.mark.parametrize("final", sorted(FINAL_STATUSES))
@pytest.mark.parametrize("target", list(TaskStatus))
def test_final_states_have_no_outgoing_transitions(final: TaskStatus, target: TaskStatus) -> None:
    t = task(final)

    with pytest.raises(OrchestratorError):
        transition(t, target)

    assert t.status == final
    assert t.final is True


def test_transition_table_matches_the_spec() -> None:
    assert TRANSITIONS == {
        TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
        TaskStatus.RUNNING: {
            TaskStatus.WAITING_CONFIRMATION,
            TaskStatus.DONE,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
        },
        TaskStatus.WAITING_CONFIRMATION: {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
        },
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", TaskStatus.DONE),
        ("partial", TaskStatus.DONE),
        ("error", TaskStatus.FAILED),
        ("cancelled", TaskStatus.CANCELLED),
        ("timeout", TaskStatus.TIMEOUT),
    ],
)
def test_result_status_maps_to_task_status(status: str, expected: TaskStatus) -> None:
    assert status_for_result(TaskResult(status=status, resumen="r")) == expected


def test_non_final_task_is_not_final() -> None:
    assert task(TaskStatus.WAITING_CONFIRMATION).final is False


def test_orchestrator_error_message_is_its_code() -> None:
    assert str(OrchestratorError("queue_full")) == "queue_full"
