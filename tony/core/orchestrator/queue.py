"""FIFO of root tasks with a bounded size and a single active slot."""

from __future__ import annotations

from collections import deque

from tony.core.orchestrator.errors import QUEUE_FULL, OrchestratorError
from tony.core.orchestrator.task import Task


class TaskQueue:
    def __init__(self, max_queued: int) -> None:
        self._max_queued = max_queued
        self._queued: deque[Task] = deque()
        self.active: Task | None = None

    @property
    def queued(self) -> list[Task]:
        return list(self._queued)

    def __len__(self) -> int:
        return len(self._queued)

    def push(self, task: Task) -> None:
        if len(self._queued) >= self._max_queued:
            raise OrchestratorError(QUEUE_FULL)
        self._queued.append(task)

    def start_next(self) -> Task | None:
        if self.active is not None or not self._queued:
            return None
        self.active = self._queued.popleft()
        return self.active

    def release(self, task: Task) -> None:
        if self.active is task:
            self.active = None

    def remove(self, task_id: str) -> bool:
        for task in self._queued:
            if task.id == task_id:
                self._queued.remove(task)
                return True
        return False
