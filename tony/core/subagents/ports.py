"""What a subagent launcher needs from whoever hosts subtasks (the orchestrator)."""

from __future__ import annotations

from typing import Protocol

from tony.core.runner import TaskRequest, TaskResult


class SubmittedTask(Protocol):
    id: str


class SubtaskHost(Protocol):
    def submit_subtask(self, parent_id: str, agent: str, request: TaskRequest) -> SubmittedTask: ...

    async def wait(self, task_id: str) -> TaskResult: ...
