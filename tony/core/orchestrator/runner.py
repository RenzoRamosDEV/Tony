import asyncio
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tony.core.config.placeholders import SecretMasker
from tony.core.config.secrets import Variables, load_variables
from tony.core.config.settings import TonyConfig, load_config
from tony.core.events import log_events
from tony.core.events.log_events import Outcome
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.guard.audit import AuditLog
from tony.core.guard.confirm import Confirmer, NoChannelConfirmer
from tony.core.guard.edith import EdithGuard
from tony.core.guard.policy import Policy, load_policy
from tony.core.guard.port import Guard
from tony.core.guard.wording import QuestionWording
from tony.core.loader.agent import AgentDefinition, load_agent
from tony.core.logging.task_log import Clock, JsonlTaskLog, new_task_id, utc_now
from tony.core.mcp.manager import McpManager
from tony.core.mcp.native import NATIVE_TOOLS, NativeTool
from tony.core.orchestrator.ports import EngineOutcome, ModelEngine
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.results import to_task_result
from tony.core.orchestrator.supervisor import TaskSupervisor

WordingFactory = Callable[[str, str], QuestionWording]
"""Builds the guard's question wording from its system prompt and resolved model id."""


@dataclass
class RunDeps:
    root: Path
    engine: ModelEngine
    guard: Guard | None = None
    confirmer: Confirmer = field(default_factory=NoChannelConfirmer)
    wording: WordingFactory | None = None
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    native: Mapping[str, NativeTool] = field(default_factory=lambda: NATIVE_TOOLS)
    clock: Clock = utc_now
    monotonic: Callable[[], float] = time.monotonic
    task_id_factory: Callable[[], str] = new_task_id
    task_timeout: float | None = None


class NotWorkerError(Exception):
    def __init__(self, agent: str, role: str) -> None:
        super().__init__(f"agent '{agent}' is not a worker (role: {role})")


@dataclass(frozen=True)
class _TaskRun:
    id: str
    agent: AgentDefinition
    model_id: str
    variables: Variables
    masker: SecretMasker
    log: JsonlTaskLog
    guard: Guard
    supervisor: TaskSupervisor


async def run_task(agent_name: str, request: TaskRequest, deps: RunDeps) -> TaskResult:
    config = load_config(deps.root)
    agent = load_agent(deps.root, agent_name, config, native_tools=deps.native.keys())
    if agent.spec.role != "worker":
        raise NotWorkerError(agent_name, agent.spec.role)
    model_id = config.resolve_model(agent.spec.model)
    guard_agent = load_agent(deps.root, config.guard, config, native_tools=deps.native.keys())
    policy = load_policy(deps.root, config.guard)
    task_id = deps.task_id_factory()
    variables = load_variables(deps.root, deps.environ)
    masker = SecretMasker(variables.env_file_values.values())
    log = JsonlTaskLog(deps.root, task_id, masker=masker, clock=deps.clock)
    run = _TaskRun(
        id=task_id,
        agent=agent,
        model_id=model_id,
        variables=variables,
        masker=masker,
        log=log,
        guard=deps.guard or _edith(deps, config, guard_agent, policy, masker),
        supervisor=TaskSupervisor(policy.limits, log),
    )
    timeout = policy.limits.task_timeout_s if deps.task_timeout is None else deps.task_timeout
    log.emit(log_events.task_started(agent_name, request))
    try:
        outcome = await asyncio.wait_for(_run_engine(run, request, deps), timeout)
    except TimeoutError:
        return _finish(log, "timeout", _failed(f"task timed out after {timeout:g} s"))
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
    masked = TaskResult.model_validate(masker.mask_json(result.model_dump()))
    return _finish(log, "error" if masked.errores else "ok", masked)


def _edith(
    deps: RunDeps,
    config: TonyConfig,
    guard_agent: AgentDefinition,
    policy: Policy,
    masker: SecretMasker,
) -> EdithGuard:
    wording = None
    if deps.wording is not None:
        guard_model = config.resolve_model(guard_agent.spec.model)
        wording = deps.wording(guard_agent.spec.system_prompt, guard_model)
    return EdithGuard(
        policy,
        confirmer=deps.confirmer,
        wording=wording,
        audit=AuditLog(deps.root, clock=deps.clock),
        masker=masker,
        monotonic=deps.monotonic,
    )


async def _run_engine(run: _TaskRun, request: TaskRequest, deps: RunDeps) -> EngineOutcome:
    async with McpManager(
        run.agent.tools,
        variables=run.variables,
        masker=run.masker,
        sink=run.log,
        log_dir=deps.root / "logs" / "mcp",
        native=deps.native,
    ) as manager:
        proxy = ToolProxy(
            task_id=run.id,
            agent=run.agent.name,
            guard=run.guard,
            caller=manager,
            sink=run.log,
            masker=run.masker,
            supervisor=run.supervisor,
        )
        tools = proxy.wrap(manager.tools)
        return await deps.engine.run(run.agent.spec, request, tools, run.model_id)


def _failed(message: str) -> TaskResult:
    return TaskResult(resumen="", errores=[message])


def _finish(log: JsonlTaskLog, outcome: Outcome, result: TaskResult) -> TaskResult:
    log.emit(log_events.task_finished(outcome, result))
    return result
