"""Orchestration of one `tony run`: config -> agent -> MCPs -> runner -> log."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.core.config import ConfigError, TonySettings, dotenv_secrets, load_env, load_settings
from tony.core.loader import AgentLoadError, AgentSpec, load_agent
from tony.core.logging import JsonlEventSink, new_task_id
from tony.core.mcp import ConfirmGate, McpServerStatus
from tony.core.orchestrator.worker import (
    ManagerFactory,
    status_payload,
)
from tony.core.runner import AgentRunner, TaskRequest, TaskResult
from tony.core.runner.claude_sdk import ClaudeSdkRunner
from tony.core.runner.proxy import ToolCaller
from tony.core.subagents.handlers import WorkerToolHandlers
from tony.core.subagents.launcher import SubagentLauncher


class RunTaskError(Exception):
    """The task could not start (bad config, unknown or unsuitable agent)."""


RunnerFactory = Callable[[TonySettings, str, ConfirmGate, ToolCaller, Any], AgentRunner]
GateFactory = Callable[[AgentSpec, TonySettings], ConfirmGate]
SUBAGENTS_UNAVAILABLE = (
    "Aviso: el agente declara 'run_subagent', pero los subagentes solo están disponibles en "
    "tony chat y en el servidor web; aquí la tool devolverá un error."
)


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
    settings: TonySettings,
    task_id: str,
    gate: ConfirmGate,
    call: ToolCaller,
    native_handlers: Any = None,
) -> AgentRunner:
    return ClaudeSdkRunner(
        settings=settings, task_id=task_id, gate=gate, call=call, native_handlers=native_handlers
    )


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
    sink = JsonlEventSink(logs_dir, task_id, [*dotenv_secrets(dotenv_path), *spec.secrets])
    events = UsageRecorder(sink)
    manager = manager_factory(settings)
    try:
        await manager.start(spec.tools)
        statuses = manager.status()
        events.emit("mcp.status", status_payload(statuses))
        handlers = WorkerToolHandlers(spec, SubagentLauncher(None, task_id, spec.subagents))
        runner = runner_factory(
            settings, task_id, gate_factory(spec, settings), manager.call, handlers
        )
        result = await runner.run(spec, TaskRequest(objetivo=task), manager.catalog, events)
    finally:
        await manager.stop()
        sink.close()
    warnings = [*mcp_warnings(statuses), *subagent_warnings(spec)]
    return RunOutcome(result, events.usage, sink.path, warnings)


def subagent_warnings(spec: AgentSpec) -> list[str]:
    return [SUBAGENTS_UNAVAILABLE] if "run_subagent" in spec.tools.native else []


def mcp_warnings(statuses: dict[str, McpServerStatus]) -> list[str]:
    return [
        f"Aviso: el MCP '{name}' no está disponible: {status.error}"
        for name, status in statuses.items()
        if status.state == "error"
    ]
