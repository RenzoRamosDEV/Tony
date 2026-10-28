"""Composition shared by every channel: settings -> agents -> memory -> orchestrator -> session.

The CLI and the web server differ only in the channel, the confirmation gate of the front
and the input loop; everything else is built here once per process.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from tony.core.channels.ports import Channel
from tony.core.channels.session import ChatSession, Memory
from tony.core.config import ConfigError, TonySettings, dotenv_secrets, load_env, load_settings
from tony.core.config.watcher import ConfigWatcher
from tony.core.loader import AgentLoadError, AgentSpec, load_agent
from tony.core.logging import JsonlEventSink
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.mcp.ports import ManagerFactory, ToolManager, default_manager_factory
from tony.core.memory.conversations import ConversationStore
from tony.core.memory.preferences import PreferencesStore
from tony.core.memory.settings import SettingsStore
from tony.core.orchestrator.clock import Clock, SystemClock
from tony.core.orchestrator.orchestrator import Orchestrator
from tony.core.orchestrator.reload import AgentReloader
from tony.core.orchestrator.worker import (
    SdkWorkerFactory,
    WorkerRunnerFactory,
    default_worker_runner_factory,
    role_mismatch_warning,
)
from tony.core.runner.conversation import ClaudeSdkConversation, ConversationRunner
from tony.core.runner.proxy import ToolCaller

ConversationFactory = Callable[[TonySettings, ConfirmGate, ToolCaller], ConversationRunner]
GateFactory = Callable[[TonySettings, AgentSpec], ConfirmGate]
SESSION_LOG_PREFIX = "chat-"


class ChatError(Exception):
    """The chat could not start (bad config or an agent that does not load)."""


@dataclass(frozen=True)
class RuntimeOptions:
    config_path: Path
    agents_dir: Path
    logs_dir: Path = Path("logs")
    memory_dir: Path = Path("memory")


def default_conversation_factory(
    settings: TonySettings, gate: ConfirmGate, call: ToolCaller
) -> ConversationRunner:
    return ClaudeSdkConversation(settings, gate, call)


class _SessionLink:
    """Follows whichever session is open: its log receives the reload events, it the notices."""

    def __init__(self) -> None:
        self.session: ChatSession | None = None
        self.log: JsonlEventSink | None = None

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.log is not None:
            self.log.emit(event_type, payload)

    async def notify(self, text: str, *event: Any) -> None:
        if self.session is not None:
            await self.session.notify_reload(text, *event)


@dataclass
class ChatRuntime:
    options: RuntimeOptions
    settings: TonySettings
    front: AgentSpec
    worker: AgentSpec
    warnings: list[str]
    secrets: list[str]
    memory: Memory
    worker_factory: SdkWorkerFactory
    orchestrator: Orchestrator
    front_manager: ToolManager | None
    front_runner: ConversationRunner
    reloader: AgentReloader
    watcher: ConfigWatcher
    clock: Clock = field(default_factory=SystemClock, repr=False)
    _link: _SessionLink = field(default_factory=_SessionLink, repr=False)

    @property
    def session(self) -> ChatSession | None:
        return self._link.session

    @property
    def session_log(self) -> JsonlEventSink | None:
        return self._link.log

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Record an event in the JSONL of the open session, if there is one."""
        self._link.emit(event_type, payload)

    async def open_session(self, conversation_id: str, channel: Channel) -> ChatSession:
        if self._link.session is not None:
            raise RuntimeError("ya hay una sesión de chat abierta")
        log = JsonlEventSink(
            self.options.logs_dir, f"{SESSION_LOG_PREFIX}{conversation_id}", self.secrets
        )
        catalog = self.front_manager.catalog if self.front_manager else ToolCatalog.empty()
        session = ChatSession(
            self.front,
            self.front_runner,
            self.orchestrator,
            channel,
            self.memory,
            self.settings,
            clock=self.clock,
            events=log,
            catalog=catalog,
            secrets=self.secrets,
        )
        self._link.log, self._link.session = log, session
        await session.start(conversation_id)
        return session

    async def close_session(self) -> None:
        session, self._link.session = self._link.session, None
        log, self._link.log = self._link.log, None
        try:
            if session is not None:
                await session.close(close_orchestrator=False)
        finally:
            if log is not None:
                log.close()

    async def aclose(self) -> None:
        async with AsyncExitStack() as stack:
            stack.callback(self.memory.conversations.close)
            if self.front_manager is not None:
                stack.push_async_callback(self.front_manager.stop)
            stack.push_async_callback(self.orchestrator.close)
            stack.push_async_callback(self.close_session)
            await self.watcher.stop()


async def build_chat_runtime(
    options: RuntimeOptions,
    gate_factory: GateFactory,
    conversation_factory: ConversationFactory = default_conversation_factory,
    manager_factory: ManagerFactory = default_manager_factory,
    runner_factory: WorkerRunnerFactory = default_worker_runner_factory,
    watch: Callable[..., Any] | None = None,
    err: TextIO | None = None,
    clock: Clock | None = None,
) -> ChatRuntime:
    clock = clock or SystemClock()
    try:
        settings = load_settings(options.config_path)
    except ConfigError as exc:
        raise ChatError(f"Configuración inválida en {options.config_path}: {exc}") from None
    dotenv_path = options.config_path.parent / ".env"
    secrets = dotenv_secrets(dotenv_path)
    env = load_env(dotenv_path)
    front, worker, warnings = load_roles(settings, options.agents_dir, env)
    for warning in warnings:
        (err or sys.stderr).write(warning + "\n")
    memory = open_memory(options.memory_dir, settings.limits.memory_max_lines)
    worker_factory = SdkWorkerFactory(
        settings, worker, options.logs_dir, secrets, manager_factory, runner_factory
    )
    front_manager = await _front_tools(front, settings, manager_factory)
    link = _SessionLink()
    reloader = AgentReloader(options.agents_dir, settings, env, worker_factory, link, link.notify)
    watcher = ConfigWatcher(options.agents_dir, reloader.reload, watch=watch)
    runtime = ChatRuntime(
        options=options,
        settings=settings,
        front=front,
        worker=worker,
        warnings=warnings,
        secrets=[*secrets, *front.secrets, *worker.secrets],
        memory=memory,
        worker_factory=worker_factory,
        orchestrator=Orchestrator(worker_factory, settings.limits, clock=clock),
        front_manager=front_manager,
        front_runner=conversation_factory(
            settings, gate_factory(settings, front), _front_call(front_manager)
        ),
        reloader=reloader,
        watcher=watcher,
        clock=clock,
        _link=link,
    )
    watcher.start()
    return runtime


def load_roles(
    settings: TonySettings, agents_dir: Path, env: dict[str, str]
) -> tuple[AgentSpec, AgentSpec, list[str]]:
    front = _load_role(settings.front, "front", agents_dir, settings, env)
    worker = _load_role(settings.worker, "worker", agents_dir, settings, env)
    warnings = [
        w
        for w in (role_mismatch_warning(front, "front"), role_mismatch_warning(worker, "worker"))
        if w
    ]
    return front, worker, warnings


def _load_role(
    name: str, role: str, agents_dir: Path, settings: TonySettings, env: dict[str, str]
) -> AgentSpec:
    folder = agents_dir / name
    if not folder.is_dir():
        raise ChatError(f"No existe el agente '{name}' ({role}) en {agents_dir}")
    try:
        return load_agent(folder, settings, env)
    except AgentLoadError as exc:
        raise ChatError(f"No se pudo cargar el agente '{name}' ({role}): {exc.message}") from None


def open_memory(memory_dir: Path, max_lines: int) -> Memory:
    return Memory(
        preferences=PreferencesStore(memory_dir / "preferences.md", max_lines=max_lines),
        settings=SettingsStore(memory_dir / "settings.json"),
        conversations=ConversationStore(memory_dir / "conversations.sqlite"),
    )


async def _front_tools(
    front: AgentSpec, settings: TonySettings, manager_factory: ManagerFactory
) -> ToolManager | None:
    if not front.tools.mcpServers:
        return None
    manager = manager_factory(settings)
    await manager.start(front.tools)
    return manager


def _front_call(manager: ToolManager | None) -> ToolCaller:
    if manager is not None:
        return manager.call

    async def no_tools(qualified, args, timeout):
        raise RuntimeError(f"el front no tiene la tool {qualified}")

    return no_tools
