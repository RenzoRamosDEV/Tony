"""Task record, its statuses and the orchestrator event names."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tony.core.runner import TaskRequest, TaskResult

TASK_QUEUED = "task.queued"
TASK_RUNNING = "task.running"
TASK_PROGRESS = "task.progress"
TASK_NEEDS_CONFIRMATION = "task.needs_confirmation"
TASK_CONFIRMED = "task.confirmed"
TASK_CANCELLED = "task.cancelled"
TASK_RESULT = "task.result"
TASK_FINISHED = "task.finished"
TOOL_CALL = "tool.call"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


FINAL_STATUSES = frozenset(
    {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT}
)

RESULT_STATUS_TO_TASK_STATUS: dict[str, TaskStatus] = {
    "ok": TaskStatus.DONE,
    "partial": TaskStatus.DONE,
    "error": TaskStatus.FAILED,
    "cancelled": TaskStatus.CANCELLED,
    "timeout": TaskStatus.TIMEOUT,
}


def status_for_result(result: TaskResult) -> TaskStatus:
    return RESULT_STATUS_TO_TASK_STATUS[result.status]


@dataclass(frozen=True)
class Event:
    task_id: str
    type: str
    payload: dict[str, Any]
    seq: int
    ts: str


@dataclass
class Task:
    id: str
    request: TaskRequest
    parent_id: str | None = None
    status: TaskStatus = TaskStatus.QUEUED
    created_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    result: TaskResult | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    finished: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def final(self) -> bool:
        return self.status in FINAL_STATUSES
