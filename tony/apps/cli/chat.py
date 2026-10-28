"""Composition of one `tony chat`: settings -> agents -> orchestrator -> session -> REPL."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from tony.apps.cli.chat_channel import CliChannel
from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.apps.cli.repl import ChatRepl
from tony.apps.cli.stdin_reader import LineSource, StdinReader
from tony.core.channels.session import CHANNEL_NAME, ChatSession, Memory
from tony.core.config import ConfigError, TonySettings, dotenv_secrets, load_env, load_settings
from tony.core.loader import AgentLoadError, AgentSpec, load_agent
from tony.core.logging import JsonlEventSink
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.memory.conversations import ConversationStore
from tony.core.memory.preferences import PreferencesStore
from tony.core.memory.settings import SettingsStore
from tony.core.orchestrator.orchestrator import Orchestrator
from tony.core.orchestrator.worker import (
    ManagerFactory,
    SdkWorkerFactory,
    ToolManager,
    WorkerRunnerFactory,
    default_manager_factory,
    default_worker_runner_factory,
    role_mismatch_warning,
)
from tony.core.runner.conversation import ClaudeSdkConversation, ConversationRunner
from tony.core.runner.proxy import ToolCaller

ConversationFactory = Callable[[TonySettings, ConfirmGate, ToolCaller], ConversationRunner]


class ChatError(Exception):
    """The chat could not start (bad config or an agent that does not load)."""


@dataclass(frozen=True)
class ChatOptions:
    config_path: Path
    agents_dir: Path
    new_conversation: bool = False
    logs_dir: Path = Path("logs")
    memory_dir: Path = Path("memory")


def default_conversation_factory(
    settings: TonySettings, gate: ConfirmGate, call: ToolCaller
) -> ConversationRunner:
    return ClaudeSdkConversation(settings, gate, call)


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


def select_conversation(memory: Memory, new_conversation: bool) -> str:
    if not new_conversation:
        last = memory.conversations.last_conversation(CHANNEL_NAME)
        if last is not None:
            return last
    return memory.conversations.start_conversation(CHANNEL_NAME)


async def run_chat(
    options: ChatOptions,
    conversation_factory: ConversationFactory = default_conversation_factory,
    manager_factory: ManagerFactory = default_manager_factory,
    runner_factory: WorkerRunnerFactory = default_worker_runner_factory,
    lines: LineSource | None = None,
    out: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    err = out or sys.stderr
    try:
        settings = load_settings(options.config_path)
    except ConfigError as exc:
        raise ChatError(f"Configuración inválida en {options.config_path}: {exc}") from None
    dotenv_path = options.config_path.parent / ".env"
    secrets = dotenv_secrets(dotenv_path)
    front, worker, warnings = load_roles(settings, options.agents_dir, load_env(dotenv_path))
    for warning in warnings:
        err.write(warning + "\n")
    lines = lines or StdinReader()
    memory = open_memory(options.memory_dir, settings.limits.memory_max_lines)
    conversation_id = select_conversation(memory, options.new_conversation)
    worker_factory = SdkWorkerFactory(
        settings, worker, options.logs_dir, secrets, manager_factory, runner_factory
    )
    orchestrator = Orchestrator(worker_factory, settings.limits)
    confirm_lock = asyncio.Lock()
    channel = CliChannel(
        worker.name.capitalize(),
        lines,
        orchestrator.confirm,
        settings.limits.confirm_timeout_s,
        out,
        stdout,
        lock=confirm_lock,
    )
    front_manager = await _front_tools(front, settings, manager_factory)
    front_gate = CliConfirmGate(
        front.name.capitalize(), settings.limits.confirm_timeout_s, lines, out, lock=confirm_lock
    )
    front_runner = conversation_factory(settings, front_gate, _front_call(front_manager))
    all_secrets = [*secrets, *front.secrets, *worker.secrets]
    session_log = JsonlEventSink(options.logs_dir, f"chat-{conversation_id}", all_secrets)
    session = ChatSession(
        front,
        front_runner,
        orchestrator,
        channel,
        memory,
        settings,
        events=session_log,
        catalog=front_manager.catalog if front_manager else ToolCatalog.empty(),
        secrets=all_secrets,
    )
    try:
        await session.start(conversation_id)
        return await ChatRepl(session, lines, memory, settings, out, stdout).run()
    finally:
        if front_manager is not None:
            await front_manager.stop()
        session_log.close()
        memory.conversations.close()


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
