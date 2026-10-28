"""Allowed task transitions; a final status has no way out."""

from __future__ import annotations

from tony.core.orchestrator.errors import INVALID_TRANSITION, OrchestratorError
from tony.core.orchestrator.task import Task, TaskStatus

TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
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


def transition(task: Task, to: TaskStatus) -> None:
    """Move the task to `to`; the caller holds `task.lock` when concurrency matters."""
    if to not in TRANSITIONS.get(task.status, set()):
        raise OrchestratorError(INVALID_TRANSITION)
    task.status = to
