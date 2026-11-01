import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tony.core.config.placeholders import SecretMasker
from tony.core.config.secrets import load_secrets
from tony.core.config.settings import load_config
from tony.core.events import log_events
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.guard.allow_all import AllowAllGuard
from tony.core.guard.port import Guard
from tony.core.loader.agent import AgentDefinition, load_agent
from tony.core.logging.task_log import Clock, JsonlTaskLog, new_task_id, utc_now
from tony.core.mcp.manager import McpManager
from tony.core.mcp.native import NATIVE_TOOLS, NativeTool
from tony.core.orchestrator.ports import EngineOutcome, ModelEngine
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.results import to_task_result


@dataclass
class RunDeps:
    root: Path
    engine: ModelEngine
    guard: Guard = field(default_factory=AllowAllGuard)
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    native: Mapping[str, NativeTool] = field(default_factory=lambda: NATIVE_TOOLS)
    clock: Clock = utc_now
    task_id_factory: Callable[[], str] = new_task_id
    task_timeout: float = 300.0


class NotWorkerError(Exception):
    def __init__(self, agent: str, role: str) -> None:
        super().__init__(f"agent '{agent}' is not a worker (role: {role})")


async def run_task(agent_name: str, request: TaskRequest, deps: RunDeps) -> TaskResult:
    config = load_config(deps.root)
    agent = load_agent(deps.root, agent_name, config, native_tools=deps.native.keys())
    if agent.spec.role != "worker":
        raise NotWorkerError(agent_name, agent.spec.role)
    model_id = config.resolve_model(agent.spec.model)
    task_id = deps.task_id_factory()
    masker = SecretMasker()
    log = JsonlTaskLog(deps.root, task_id, masker=masker, clock=deps.clock)
    log.emit(log_events.task_started(agent_name, request))
    try:
        outcome = await asyncio.wait_for(
            _run_engine(agent, request, model_id, task_id, deps, masker, log), deps.task_timeout
        )
    except TimeoutError:
        return _finish(log, "timeout", _failed(f"task timed out after {deps.task_timeout:g} s"))
    except Exception as error:
        message = str(error) or type(error).__name__
        log.emit(log_events.error("engine", message))
        return _finish(log, "error", _failed(message))
    for usage in outcome.usage:
        log.emit(
            log_events.token_usage(
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
            )
        )
    result = to_task_result(outcome)
    masked = TaskResult.model_validate(masker.mask_json(result.model_dump(mode="json")))
    return _finish(log, "error" if masked.errores else "ok", masked)


async def _run_engine(
    agent: AgentDefinition,
    request: TaskRequest,
    model_id: str,
    task_id: str,
    deps: RunDeps,
    masker: SecretMasker,
    log: JsonlTaskLog,
) -> EngineOutcome:
    async with McpManager(
        agent.tools,
        variables=load_secrets(deps.root, deps.environ),
        masker=masker,
        sink=log,
        log_dir=deps.root / "logs" / "mcp",
        native=deps.native,
    ) as manager:
        proxy = ToolProxy(
            task_id=task_id,
            agent=agent.name,
            guard=deps.guard,
            caller=manager,
            sink=log,
            masker=masker,
        )
        return await deps.engine.run(agent.spec, request, proxy.wrap(manager.tools), model_id)


def _failed(message: str) -> TaskResult:
    return TaskResult(resumen="", errores=[message])


def _finish(log: JsonlTaskLog, outcome: str, result: TaskResult) -> TaskResult:
    log.emit(log_events.task_finished(outcome, result))
    return result
