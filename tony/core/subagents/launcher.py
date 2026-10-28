"""`run_subagent` handler: one subtask per call, at most two in flight per parent task."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from tony.core.loader import AgentSpec
from tony.core.runner import TaskRequest, TaskResult
from tony.core.subagents.ports import SubtaskHost

MAX_CONCURRENT = 2
NO_HOST_ERROR = "run_subagent solo está disponible en tony chat y en el servidor web"


class SubagentLauncher:
    def __init__(
        self,
        host: SubtaskHost | None,
        parent_id: str,
        subagents: Mapping[str, AgentSpec],
        limit: int = MAX_CONCURRENT,
        tool_timeout_s: float | None = None,
    ) -> None:
        self._host = host
        self._parent_id = parent_id
        self._subagents = subagents
        self._slots = asyncio.Semaphore(limit)

    async def run_subagent(self, name: str, request: TaskRequest) -> TaskResult:
        if name not in self._subagents:
            return _error(_unknown_message(name, self._subagents))
        if self._host is None:
            return _error(NO_HOST_ERROR)
        async with self._slots:
            task = self._host.submit_subtask(self._parent_id, name, request)
            return await self._host.wait(task.id)


def _unknown_message(name: str, subagents: Mapping[str, AgentSpec]) -> str:
    available = ", ".join(sorted(subagents)) or "ninguno"
    return f"subagente '{name}' desconocido; disponibles: {available}"


def _error(message: str) -> TaskResult:
    return TaskResult(
        status="error", resumen=f"No se pudo ejecutar el subagente: {message}", errores=[message]
    )
