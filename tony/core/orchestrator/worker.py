"""Builds the worker side of a task: MCP generation, JSONL log, native handlers and runner.

Root tasks lease the current MCP generation; subtasks reuse their root's generation and
are built by `SubagentWorkerBuilder` with the intersected permissions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.logging import JsonlEventSink
from tony.core.mcp import ConfirmGate, McpServerStatus
from tony.core.mcp.generations import Generation, McpGenerationPool
from tony.core.mcp.ports import ManagerFactory, ToolManager, default_manager_factory
from tony.core.orchestrator.ports import Worker
from tony.core.orchestrator.task import Task
from tony.core.runner import EventSink
from tony.core.runner.cancel import CancelToken
from tony.core.runner.claude_sdk import CLEANUP_BUDGET_S
from tony.core.runner.factory import WorkerRunnerFactory, default_worker_runner_factory
from tony.core.subagents.builder import ChildWorker, SubagentWorkerBuilder
from tony.core.subagents.handlers import WorkerToolHandlers
from tony.core.subagents.launcher import SubagentLauncher
from tony.core.subagents.ports import SubtaskHost

__all__ = [
    "ManagerFactory",
    "SdkWorkerFactory",
    "ToolManager",
    "WorkerRunnerFactory",
    "default_manager_factory",
    "default_worker_runner_factory",
    "role_mismatch_warning",
    "status_payload",
]


def role_mismatch_warning(spec: AgentSpec, expected_role: str) -> str | None:
    if spec.role == expected_role:
        return None
    return (
        f"Aviso: el agente '{spec.name}' tiene role '{spec.role}' "
        f"pero se usa como '{expected_role}'"
    )


def status_payload(statuses: dict[str, McpServerStatus]) -> dict[str, Any]:
    return {
        name: {"state": status.state, "error": status.error, "tool_count": status.tool_count}
        for name, status in statuses.items()
    }


class SdkWorkerFactory:
    def __init__(
        self,
        settings: TonySettings,
        spec: AgentSpec,
        logs_dir: Path,
        secrets: list[str],
        manager_factory: ManagerFactory = default_manager_factory,
        runner_factory: WorkerRunnerFactory = default_worker_runner_factory,
        close_budget_s: float = CLEANUP_BUDGET_S,
    ) -> None:
        self._settings = settings
        self._logs_dir = logs_dir
        self._dotenv_secrets = list(secrets)
        self._runner_factory = runner_factory
        self.pool = McpGenerationPool(manager_factory, settings, spec.tools, close_budget_s)
        self._builder = SubagentWorkerBuilder(
            settings, runner_factory, manager_factory, close_budget_s
        )
        self._host: SubtaskHost | None = None
        self._leases: dict[str, Generation] = {}
        self._children: dict[str, ChildWorker] = {}
        self.update_spec(spec)

    def update_spec(self, spec: AgentSpec) -> None:
        """Tasks built from now on use this spec (tools, secrets, skills, subagents)."""
        self._spec = spec
        self._secrets = [*self._dotenv_secrets, *spec.secrets]
        self.warnings = [w for w in [role_mismatch_warning(spec, "worker")] if w]

    def attach_host(self, host: SubtaskHost) -> None:
        self._host = host

    def open_log(self, task_id: str, parent_id: str | None = None) -> JsonlEventSink:
        return JsonlEventSink(self._logs_dir, task_id, self._secrets, parent_id)

    async def build_worker(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        if task.agent is None:
            return await self._build_root(task, events, cancel_token, gate)
        return await self._build_child(task, cancel_token, gate)

    async def release(self, task_id: str) -> None:
        generation = self._leases.pop(task_id, None)
        if generation is not None:
            await self.pool.release(generation)
        child = self._children.pop(task_id, None)
        if child is not None:
            await child.close()

    async def close(self) -> None:
        await self.pool.close_all()

    async def _build_root(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        generation = await self.pool.acquire()
        self._leases[task.id] = generation
        manager = generation.manager
        events.emit("mcp.status", status_payload(manager.status()))
        launcher = SubagentLauncher(self._host, task.id, self._spec.subagents)
        handlers = WorkerToolHandlers(self._spec, launcher)
        runner = self._runner_factory(
            self._settings, task.id, gate, manager.call, cancel_token, handlers
        )
        return Worker(runner=runner, spec=self._spec, catalog=manager.catalog)

    async def _build_child(
        self, task: Task, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        child_spec = self._spec.subagents.get(task.agent or "")
        if child_spec is None:
            raise LookupError(f"subagente '{task.agent}' desconocido")
        generation = self._leases.get(task.parent_id or "")
        if generation is None:
            raise LookupError(f"la tarea padre '{task.parent_id}' no tiene generación de MCPs")
        child = await self._builder.build(
            self._spec, child_spec, generation.manager, gate, cancel_token, task.id
        )
        self._children[task.id] = child
        return Worker(runner=child.runner, spec=child.spec, catalog=child.catalog)
