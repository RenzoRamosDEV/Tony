"""Builds the worker side of a task: shared MCP manager, JSONL log and SDK runner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec, ToolConfig
from tony.core.logging import JsonlEventSink
from tony.core.mcp import ConfirmGate, McpManager, McpServerStatus, ToolCallOutcome, ToolCatalog
from tony.core.orchestrator.ports import Worker
from tony.core.orchestrator.task import Task
from tony.core.runner import AgentRunner, EventSink
from tony.core.runner.cancel import CancelToken
from tony.core.runner.claude_sdk import ClaudeSdkRunner
from tony.core.runner.proxy import ToolCaller


class ToolManager(Protocol):
    catalog: ToolCatalog

    async def start(
        self, tool_config: ToolConfig, server_filter: list[str] | None = None
    ) -> None: ...

    async def call(
        self, qualified: str, args: dict[str, Any], timeout: float
    ) -> ToolCallOutcome: ...

    def status(self) -> dict[str, McpServerStatus]: ...

    async def stop(self) -> None: ...


ManagerFactory = Callable[[TonySettings], ToolManager]
WorkerRunnerFactory = Callable[
    [TonySettings, str, ConfirmGate, ToolCaller, CancelToken], AgentRunner
]


def default_manager_factory(settings: TonySettings) -> ToolManager:
    return McpManager(connect_timeout_s=settings.limits.mcp_connect_timeout_s)


def default_worker_runner_factory(
    settings: TonySettings, task_id: str, gate: ConfirmGate, call: ToolCaller, token: CancelToken
) -> AgentRunner:
    return ClaudeSdkRunner(
        settings=settings, task_id=task_id, gate=gate, call=call, cancel_token=token
    )


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
    ) -> None:
        self._settings = settings
        self._spec = spec
        self._logs_dir = logs_dir
        self._secrets = [*secrets, *spec.secrets]
        self._manager_factory = manager_factory
        self._runner_factory = runner_factory
        self._manager: ToolManager | None = None
        self.warnings = [w for w in [role_mismatch_warning(spec, "worker")] if w]

    def open_log(self, task_id: str) -> JsonlEventSink:
        return JsonlEventSink(self._logs_dir, task_id, self._secrets)

    async def build_worker(
        self, task: Task, events: EventSink, cancel_token: CancelToken, gate: ConfirmGate
    ) -> Worker:
        manager = await self._started_manager()
        events.emit("mcp.status", status_payload(manager.status()))
        runner = self._runner_factory(self._settings, task.id, gate, manager.call, cancel_token)
        return Worker(runner=runner, spec=self._spec, catalog=manager.catalog)

    async def close(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None

    async def _started_manager(self) -> ToolManager:
        if self._manager is None:
            manager = self._manager_factory(self._settings)
            await manager.start(self._spec.tools)
            self._manager = manager
        return self._manager
