import asyncio
import os
import time
import uuid
from asyncio import FIRST_COMPLETED
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any

from tony.core.clarification.port import Clarifier, NoChannelClarifier
from tony.core.clarification.request import ClarificationRequest
from tony.core.config.errors import DefinitionError
from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import PolicySource, StaticPolicy, ToolSpecSource
from tony.core.config.secrets import Variables, load_variables
from tony.core.config.settings import TonyConfig, load_config
from tony.core.events import core_events, log_events
from tony.core.events.core_events import Event, MaskingPublisher, Publisher
from tony.core.events.log_events import Outcome, TaskOrigin
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.evidence.apply import apply_evidence
from tony.core.evidence.observed import ObservedTexts
from tony.core.guard.audit import AuditLog
from tony.core.guard.confirm import Confirmer, NoChannelConfirmer
from tony.core.guard.edith import EdithGuard
from tony.core.guard.policy import Policy, load_policy_with_version
from tony.core.guard.port import Guard
from tony.core.guard.wording import QuestionWording
from tony.core.loader.agent import AgentDefinition, load_agent
from tony.core.loader.agent_md import AgentSpec
from tony.core.loader.subagents import list_subagents, load_subagent
from tony.core.logging.task_log import Clock, JsonlTaskLog, new_task_id, utc_now
from tony.core.mcp.manager import McpManager
from tony.core.mcp.native import NativeFactory, NativeScope, NativeTool
from tony.core.orchestrator.natives import NATIVE_TOOLS, not_found
from tony.core.orchestrator.ports import (
    ActionRecorder,
    ActionSnapshots,
    EngineOutcome,
    EventSink,
    ModelEngine,
    ProxiedTool,
    ToolReply,
    Usage,
)
from tony.core.orchestrator.prompt_sections import agent_prompt
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.results import to_task_result
from tony.core.orchestrator.supervisor import USER_CANCELLED, TaskSupervisor

SKILLS_SOURCE = "skills"

WordingFactory = Callable[[str, str], QuestionWording]
"""Builds the guard's question wording from its system prompt and resolved model id."""


@dataclass
class RunDeps:
    root: Path
    engine: ModelEngine
    guard: Guard | None = None
    confirmer: Confirmer = field(default_factory=NoChannelConfirmer)
    clarifier: Clarifier = field(default_factory=NoChannelClarifier)
    wording: WordingFactory | None = None
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    native: Mapping[str, NativeFactory] = field(default_factory=lambda: NATIVE_TOOLS)
    clock: Clock = utc_now
    monotonic: Callable[[], float] = time.monotonic
    task_id_factory: Callable[[], str] = new_task_id
    task_timeout: float | None = None
    publish: Publisher = core_events.no_op
    user_cancel: asyncio.Event | None = None
    policy_source: PolicySource | None = None
    """Live policy of a long-running host; None reads `policy.yaml` from disk per task."""
    tool_specs: ToolSpecSource | None = None
    """Live tool declarations of a long-running host; None reads `tool.json` per task."""
    journal: ActionRecorder | None = None
    """Where guarded executions are recorded; None disables the action journal."""
    snapshots: ActionSnapshots | None = None
    """Keeps pre-images of file writes for undo; None disables them."""


class NotWorkerError(Exception):
    def __init__(self, agent: str, role: str) -> None:
        super().__init__(f"agent '{agent}' is not a worker (role: {role})")


class ToolUnavailableError(Exception):
    def __init__(self, agent: str, tool_id: str) -> None:
        super().__init__(f"agent '{agent}' has no tool {tool_id}")


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
    publish: Publisher
    policy: Policy
    config: TonyConfig
    usage: list[Usage] = field(default_factory=list)
    observed: ObservedTexts = field(default_factory=ObservedTexts)


def _prepare_run(agent: AgentDefinition, config: TonyConfig, deps: RunDeps) -> _TaskRun:
    model_id = config.resolve_model(agent.spec.model)
    guard_agent = load_agent(deps.root, config.guard, config, native_tools=deps.native.keys())
    policy_source = deps.policy_source or StaticPolicy(
        *load_policy_with_version(deps.root, config.guard)
    )
    policy = policy_source.current()
    task_id = deps.task_id_factory()
    variables = load_variables(deps.root, deps.environ)
    masker = SecretMasker(variables.env_file_values.values())
    log = JsonlTaskLog(deps.root, task_id, masker=masker, clock=deps.clock)
    publish = MaskingPublisher(masker, deps.publish)
    return _TaskRun(
        id=task_id,
        agent=agent,
        model_id=model_id,
        variables=variables,
        masker=masker,
        log=log,
        guard=deps.guard or _edith(deps, config, guard_agent, policy_source, masker),
        supervisor=TaskSupervisor(policy.limits, _AlertTee(log, publish, task_id, deps.clock)),
        publish=publish,
        policy=policy,
        config=config,
    )


async def run_task(
    agent_name: str,
    request: TaskRequest,
    deps: RunDeps,
    *,
    origin: TaskOrigin | None = None,
    resumed_from: str | None = None,
) -> TaskResult:
    config, agent = _load_worker(agent_name, deps)
    run = _prepare_run(agent, config, deps)
    limits = run.policy.limits
    timeout = limits.task_timeout_s if deps.task_timeout is None else deps.task_timeout
    started = deps.monotonic()
    run.log.emit(
        log_events.task_started(agent_name, request, origin=origin, resumed_from=resumed_from)
    )
    run.publish(
        core_events.task_started(
            run.id, agent_name, request.objetivo, origin=origin, clock=deps.clock
        )
    )
    try:
        outcome, result = await _execute(run, request, deps, timeout)
    except asyncio.CancelledError:
        _finish(run, "cancelled", _failed(USER_CANCELLED), started, deps)
        raise
    return _finish(run, outcome, result, started, deps)


async def run_guarded_call(
    agent_name: str, tool_id: str, args: dict[str, Any], deps: RunDeps, *, objetivo: str
) -> ToolReply:
    """One tool call by a worker, with the guard, limits, journal and task log of any task."""
    config, agent = _load_worker(agent_name, deps)
    run = _prepare_run(agent, config, deps)
    started = deps.monotonic()
    run.log.emit(log_events.task_started(agent_name, TaskRequest(objetivo=objetivo)))
    run.publish(core_events.task_started(run.id, agent_name, objetivo, clock=deps.clock))
    try:
        async with _proxied_tools(run, deps) as tools:
            tool = next((tool for tool in tools if tool.id == tool_id), None)
            if tool is None:
                raise ToolUnavailableError(agent_name, tool_id)
            reply = await tool.handler(args)
    except asyncio.CancelledError:
        _finish(run, "cancelled", _failed(USER_CANCELLED), started, deps)
        raise
    except ToolUnavailableError:
        _finish(run, "error", _failed(f"tool {tool_id} is not available"), started, deps)
        raise
    if reply.is_error:
        _finish(run, "error", _failed(reply.text), started, deps)
    else:
        _finish(run, "ok", TaskResult(resumen=reply.text), started, deps)
    return reply


def _load_worker(agent_name: str, deps: RunDeps) -> tuple[TonyConfig, AgentDefinition]:
    config = load_config(deps.root)
    agent = load_agent(
        deps.root,
        agent_name,
        config,
        native_tools=deps.native.keys(),
        tools=deps.tool_specs.spec_for(agent_name) if deps.tool_specs is not None else None,
    )
    if agent.spec.role != "worker":
        raise NotWorkerError(agent_name, agent.spec.role)
    return config, agent


def _finish(
    run: _TaskRun, outcome: Outcome, result: TaskResult, started: float, deps: RunDeps
) -> TaskResult:
    run.log.emit(log_events.task_finished(outcome, result))
    run.publish(
        core_events.task_result(
            run.id,
            run.agent.name,
            outcome,
            result,
            input_tokens=sum(item.input_tokens for item in run.usage),
            output_tokens=sum(item.output_tokens for item in run.usage),
            elapsed_ms=round((deps.monotonic() - started) * 1000),
            clock=deps.clock,
        )
    )
    return result


async def _execute(
    run: _TaskRun, request: TaskRequest, deps: RunDeps, timeout: float
) -> tuple[Outcome, TaskResult]:
    engine = asyncio.create_task(_run_engine(run, request, deps))
    finished = await _race(engine, run.supervisor, timeout, deps.user_cancel)
    if run.supervisor.cancelled.is_set():
        return "cancelled", _failed(run.supervisor.reason)
    if not finished:
        return "timeout", _failed(f"task timed out after {timeout:g} s")
    try:
        return _engine_result(run, engine.result())
    except Exception as error:
        return _engine_failed(run, error)


def _engine_result(run: _TaskRun, outcome: EngineOutcome) -> tuple[Outcome, TaskResult]:
    for usage in outcome.usage:
        run.log.emit(
            log_events.token_usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
                cost_usd=usage.cost_usd,
            )
        )
        run.supervisor.record_usage(
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
        )
        run.usage.append(usage)
    result = to_task_result(outcome)
    masked = TaskResult.model_validate(run.masker.mask_json(result.model_dump()))
    masked = apply_evidence(masked, run.observed.texts())
    return ("error" if masked.errores else "ok"), masked


def _engine_failed(run: _TaskRun, error: Exception) -> tuple[Outcome, TaskResult]:
    message = str(error) or type(error).__name__
    run.log.emit(log_events.error("engine", message))
    return "error", _failed(message)


async def _run_subagent(
    parent: _TaskRun, deps: RunDeps, name: str, request: TaskRequest
) -> ToolReply:
    """Run a subagent inside the parent task: same id, log, guard, supervisor and usage."""
    try:
        agent = load_subagent(
            deps.root,
            parent.agent.name,
            name,
            parent.config,
            native_tools=deps.native.keys(),
            tools_for=deps.tool_specs.spec_for if deps.tool_specs is not None else None,
        )
    except DefinitionError as error:
        return ToolReply(text=str(error), is_error=True)
    if agent is None:
        listed = list_subagents(deps.root, parent.agent.name, parent.config)
        return not_found("subagent", name, [listed_name for listed_name, _ in listed])
    child = replace(parent, agent=agent, model_id=parent.config.resolve_model(agent.spec.model))
    child.log.emit(log_events.subagent_started(agent.name, request))
    try:
        outcome, result = _engine_result(child, await _run_engine(child, request, deps))
    except Exception as error:
        outcome, result = _engine_failed(child, error)
    child.log.emit(log_events.subagent_finished(agent.name, outcome, result))
    return ToolReply(text=result.model_dump_json(), is_error=bool(result.errores))


class _AlertTee:
    """Supervisor sink: every event goes to the task log; token alerts are also published."""

    def __init__(self, log: EventSink, publish: Publisher, task_id: str, clock: Clock) -> None:
        self._log = log
        self._publish = publish
        self._task_id = task_id
        self._clock = clock

    def emit(self, event: Event) -> None:
        self._log.emit(event)
        if event["type"] == "token_alert":
            self._publish(
                core_events.token_alert(
                    self._task_id,
                    total_tokens=event["total_tokens"],
                    limit=event["limit"],
                    clock=self._clock,
                )
            )


async def _race(
    engine: "asyncio.Task[EngineOutcome]",
    supervisor: TaskSupervisor,
    timeout: float,
    user_cancel: asyncio.Event | None,
) -> bool:
    """Wait for the engine, a cancellation or the timeout; stop the engine unless it finished.

    Cancelling the engine task unwinds the McpManager context, closing every server.
    """
    waiters = [asyncio.create_task(supervisor.cancelled.wait())]
    if user_cancel is not None:
        waiters.append(asyncio.create_task(user_cancel.wait()))
    try:
        await asyncio.wait({engine, *waiters}, timeout=timeout, return_when=FIRST_COMPLETED)
    except asyncio.CancelledError:
        engine.cancel()
        await asyncio.gather(engine, return_exceptions=True)
        raise
    finally:
        for waiter in waiters:
            waiter.cancel()
    if user_cancel is not None and user_cancel.is_set():
        supervisor.cancel(USER_CANCELLED)
    if engine.done() and not supervisor.cancelled.is_set():
        return True
    engine.cancel()
    await asyncio.gather(engine, return_exceptions=True)
    return False


def _edith(
    deps: RunDeps,
    config: TonyConfig,
    guard_agent: AgentDefinition,
    policy_source: PolicySource,
    masker: SecretMasker,
) -> EdithGuard:
    wording = None
    if deps.wording is not None:
        guard_model = config.resolve_model(guard_agent.spec.model)
        wording = deps.wording(guard_agent.spec.system_prompt, guard_model)
    return EdithGuard(
        policy_source,
        confirmer=deps.confirmer,
        wording=wording,
        audit=AuditLog(deps.root, clock=deps.clock),
        masker=masker,
        monotonic=deps.monotonic,
    )


def with_live_tools(agent: AgentDefinition, deps: RunDeps) -> AgentDefinition:
    """The agent with its current live tool declaration, when the host keeps one."""
    if deps.tool_specs is None:
        return agent
    return replace(agent, tools=deps.tool_specs.spec_for(agent.name))


@asynccontextmanager
async def agent_tools(
    agent: AgentDefinition, config: TonyConfig, deps: RunDeps
) -> AsyncIterator[list[ProxiedTool]]:
    """The agent's own MCP and native tools, proxied through the guard like a worker's.

    An agent declaring none gets an empty list without a task log or any connection.
    """
    if not agent.tools.mcp_servers and not agent.tools.native:
        yield []
        return
    async with _proxied_tools(_prepare_run(agent, config, deps), deps) as tools:
        yield tools


async def _run_engine(run: _TaskRun, request: TaskRequest, deps: RunDeps) -> EngineOutcome:
    spec = _spec_with_sections(run, deps)
    async with _proxied_tools(run, deps) as tools:
        return await deps.engine.run(spec, request, tools, run.model_id)


def _spec_with_sections(run: _TaskRun, deps: RunDeps) -> AgentSpec:
    prompt, errors = agent_prompt(deps.root, run.agent, run.config)
    for error in errors:
        run.log.emit(log_events.error(SKILLS_SOURCE, str(error)))
        run.publish(core_events.error(SKILLS_SOURCE, str(error), clock=deps.clock))
    return run.agent.spec.model_copy(update={"system_prompt": prompt})


@asynccontextmanager
async def _proxied_tools(run: _TaskRun, deps: RunDeps) -> AsyncIterator[list[ProxiedTool]]:
    async with McpManager(
        run.agent.tools,
        variables=run.variables,
        masker=run.masker,
        sink=run.log,
        log_dir=deps.root / "logs" / "mcp",
        native=_bind_natives(run, deps),
        on_status=lambda server, status: run.publish(
            core_events.mcp_status(
                run.agent.name, server, up=status.up, reason=status.reason, clock=deps.clock
            )
        ),
    ) as manager:
        proxy = ToolProxy(
            task_id=run.id,
            agent=run.agent.name,
            guard=run.guard,
            caller=manager,
            sink=run.log,
            masker=run.masker,
            supervisor=run.supervisor,
            publish=run.publish,
            clock=deps.clock,
            journal=deps.journal,
            snapshots=deps.snapshots,
            observed=run.observed,
        )
        yield proxy.wrap(manager.tools)


def _bind_natives(run: _TaskRun, deps: RunDeps) -> dict[str, NativeTool]:
    scope = NativeScope(
        root=deps.root,
        agent=run.agent.name,
        run_subagent=partial(_run_subagent, run, deps),
        ask_user=partial(_ask_user, run, deps),
    )
    return {name: deps.native[name](scope) for name in run.agent.tools.native}


async def _ask_user(run: _TaskRun, deps: RunDeps, question: str, options: list[str]) -> str | None:
    """Ask the user through the clarifier; None when there is no usable answer in time.

    An answer is information for the model only: it never reaches the guard.
    """
    request = ClarificationRequest(
        request_id=uuid.uuid4().hex,
        task_id=run.id,
        agent=run.agent.name,
        question=run.masker.mask(question),
        options=[run.masker.mask(option) for option in options],
    )
    asking = asyncio.create_task(deps.clarifier.ask(request))
    cancelled = asyncio.create_task(run.supervisor.cancelled.wait())
    try:
        await asyncio.wait(
            {asking, cancelled},
            timeout=run.policy.limits.confirm_timeout_s,
            return_when=FIRST_COMPLETED,
        )
        if not asking.done() or asking.cancelled() or asking.exception() is not None:
            return None
        answer = asking.result()
        return answer if answer and answer.strip() else None
    finally:
        cancelled.cancel()
        if not asking.done():
            asking.cancel()
            await asyncio.gather(asking, return_exceptions=True)


def _failed(message: str) -> TaskResult:
    return TaskResult(resumen="", errores=[message])
