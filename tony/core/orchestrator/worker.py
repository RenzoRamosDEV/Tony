"""Builds the worker side of a task: MCP generation, JSONL log, native handlers and runner.

Root tasks lease the current MCP generation together with the spec in force at that moment;
subtasks are built from their root's snapshot (never from a reloaded spec), hold their own
lease on that generation and are built by `SubagentWorkerBuilder` with the intersected
permissions.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class _Lease:
    spec: AgentSpec
    generation: Generation


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
        self._secrets = list(secrets)
        self._runner_factory = runner_factory
        self.pool = McpGenerationPool(manager_factory, settings, spec.tools, close_budget_s)
        self._builder = SubagentWorkerBuilder(
            settings, runner_factory, manager_factory, close_budget_s
        )
        self._host: SubtaskHost | None = None
        self._leases: dict[str, _Lease] = {}
        self._children: dict[str, ChildWorker] = {}
        self.update_spec(spec)

    def update_spec(self, spec: AgentSpec) -> None:
        """Tasks built from now on use this spec (tools, secrets, skills, subagents).

        Secrets only accumulate: logs of tasks still running on an older spec keep redacting.
        """
        self._spec = spec
        self._secrets.extend(s for s in spec.all_secrets() if s not in self._secrets)
        self.warnings = [w for w in [role_mismatch_warning(spec, "worker")] if w]

    async def reload_spec(self, spec: AgentSpec) -> None:
        """Start the generation of `spec.tools` and publish spec and generation together."""
        await self.pool.swap(spec.tools, on_publish=lambda: self.update_spec(spec))

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
        lease = self._leases.pop(task_id, None)
        if lease is not None:
            await self.pool.release(lease.generation)
        child = self._children.pop(task_id, None)
        if child is not None:
            await child.close()

    async def close(self) -> None:
        await self.pool.close_all()

    async def _build_root(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        generation = await self.pool.acquire()
        spec = self._spec
        self._leases[task.id] = _Lease(spec, generation)
        manager = generation.manager
        events.emit("mcp.status", status_payload(manager.status()))
        launcher = SubagentLauncher(self._host, task.id, spec.subagents)
        handlers = WorkerToolHandlers(spec, launcher)
        runner = self._runner_factory(
            self._settings, task.id, gate, manager.call, cancel_token, handlers
        )
        return Worker(runner=runner, spec=spec, catalog=manager.catalog)

    async def _build_child(
        self, task: Task, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        lease = self._leases.get(task.parent_id or "")
        if lease is None:
            raise LookupError(f"la tarea padre '{task.parent_id}' no tiene generación de MCPs")
        child_spec = lease.spec.subagents.get(task.agent or "")
        if child_spec is None:
            raise LookupError(f"subagente '{task.agent}' desconocido")
        self.pool.lease(lease.generation)
        self._leases[task.id] = lease
        child = await self._builder.build(
            lease.spec, child_spec, lease.generation.manager, gate, cancel_token, task.id
        )
        self._children[task.id] = child
        return Worker(runner=child.runner, spec=child.spec, catalog=child.catalog)
