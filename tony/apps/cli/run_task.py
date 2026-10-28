"""Orchestration of one `tony run`: config -> agent -> MCPs -> runner -> log."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.core.config import ConfigError, TonySettings, dotenv_secrets, load_env, load_settings
from tony.core.loader import AgentLoadError, AgentSpec, ToolConfig, load_agent
from tony.core.logging import JsonlEventSink, new_task_id
from tony.core.mcp import ConfirmGate, McpManager, McpServerStatus, ToolCallOutcome, ToolCatalog
from tony.core.runner import AgentRunner, TaskRequest, TaskResult
from tony.core.runner.claude_sdk import ClaudeSdkRunner
from tony.core.runner.proxy import ToolCaller


class RunTaskError(Exception):
    """The task could not start (bad config, unknown or unsuitable agent)."""


class ToolManager(Protocol):
    catalog: ToolCatalog

    async def start(
        self, tool_config: ToolConfig, server_filter: list[str] | None = None
    ) -> None: ...
    async def call(
        self, qualified: str, args: dict[str, Any], timeout: float
    ) -> ToolCallOutcome: ...
    async def stop(self) -> None: ...


RunnerFactory = Callable[[TonySettings, str, ConfirmGate, ToolCaller], AgentRunner]
ManagerFactory = Callable[[TonySettings], ToolManager]
GateFactory = Callable[[AgentSpec, TonySettings], ConfirmGate]


@dataclass
class RunOutcome:
    result: TaskResult
    usage: dict[str, Any]
    log_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass
class UsageRecorder:
    """EventSink decorator that remembers the usage reported by task.finished."""

    inner: JsonlEventSink
    usage: dict[str, Any] = field(default_factory=dict)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.inner.emit(event_type, payload)
        if event_type == "task.finished":
            self.usage = dict(payload.get("usage") or {})


def default_runner_factory(
    settings: TonySettings, task_id: str, gate: ConfirmGate, call: ToolCaller
) -> AgentRunner:
    return ClaudeSdkRunner(settings=settings, task_id=task_id, gate=gate, call=call)


def default_manager_factory(settings: TonySettings) -> ToolManager:
    return McpManager(connect_timeout_s=settings.limits.mcp_connect_timeout_s)


def default_gate_factory(spec: AgentSpec, settings: TonySettings) -> ConfirmGate:
    return CliConfirmGate(spec.name.capitalize(), settings.limits.confirm_timeout_s)


def select_worker(
    agent: str, agents_dir: Path, settings: TonySettings, env: dict[str, str]
) -> AgentSpec:
    folder = agents_dir / agent
    if not folder.is_dir():
        raise RunTaskError(f"No existe el agente '{agent}' en {agents_dir}")
    try:
        spec = load_agent(folder, settings, env)
    except AgentLoadError as exc:
        raise RunTaskError(f"No se pudo cargar el agente '{agent}': {exc.message}") from None
    if spec.role != "worker":
        raise RunTaskError(f"El agente '{agent}' no es un agente worker (rol: {spec.role})")
    return spec


async def run_task(
    agent: str,
    task: str,
    agents_dir: Path,
    config_path: Path,
    runner_factory: RunnerFactory,
    manager_factory: ManagerFactory,
    gate_factory: GateFactory = default_gate_factory,
    logs_dir: Path = Path("logs"),
) -> RunOutcome:
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise RunTaskError(f"Configuración inválida en {config_path}: {exc}") from None
    dotenv_path = config_path.parent / ".env"
    spec = select_worker(agent, agents_dir, settings, load_env(dotenv_path))

    task_id = new_task_id()
    sink = JsonlEventSink(logs_dir, task_id, dotenv_secrets(dotenv_path))
    events = UsageRecorder(sink)
    manager = manager_factory(settings)
    try:
        await manager.start(spec.tools)
        statuses = manager.status()
        events.emit("mcp.status", status_payload(statuses))
        runner = runner_factory(settings, task_id, gate_factory(spec, settings), manager.call)
        result = await runner.run(spec, TaskRequest(objetivo=task), manager.catalog, events)
    finally:
        await manager.stop()
        sink.close()
    return RunOutcome(result, events.usage, sink.path, mcp_warnings(statuses))


def status_payload(statuses: dict[str, McpServerStatus]) -> dict[str, Any]:
    return {
        name: {"state": status.state, "error": status.error, "tool_count": status.tool_count}
        for name, status in statuses.items()
    }


def mcp_warnings(statuses: dict[str, McpServerStatus]) -> list[str]:
    return [
        f"Aviso: el MCP '{name}' no está disponible: {status.error}"
        for name, status in statuses.items()
        if status.state == "error"
    ]
