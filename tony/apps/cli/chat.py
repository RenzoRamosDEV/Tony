"""Composition of one `tony chat`: the shared runtime plus terminal channel, gate and REPL."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from tony.apps.cli.chat_channel import CliChannel
from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.apps.cli.repl import ChatRepl
from tony.apps.cli.stdin_dispatcher import StdinDispatcher
from tony.apps.cli.stdin_reader import LineSource, StdinReader
from tony.core.channels.bootstrap import (
    ChatError,
    ConversationFactory,
    RuntimeOptions,
    build_chat_runtime,
    default_conversation_factory,
    load_roles,
)
from tony.core.channels.session import CHANNEL_NAME, Memory
from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp.ports import ManagerFactory, default_manager_factory
from tony.core.orchestrator.worker import WorkerRunnerFactory, default_worker_runner_factory

__all__ = [
    "ChatError",
    "ChatOptions",
    "ConversationFactory",
    "default_conversation_factory",
    "load_roles",
    "run_chat",
    "select_conversation",
]


@dataclass(frozen=True)
class ChatOptions:
    config_path: Path
    agents_dir: Path
    new_conversation: bool = False
    logs_dir: Path = Path("logs")
    memory_dir: Path = Path("memory")

    @property
    def runtime(self) -> RuntimeOptions:
        return RuntimeOptions(self.config_path, self.agents_dir, self.logs_dir, self.memory_dir)


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
    watch: Callable[..., Any] | None = None,
) -> int:
    stdin = StdinDispatcher(lines or StdinReader(), out)
    confirm_lock = asyncio.Lock()

    def gate_factory(settings: TonySettings, front: AgentSpec) -> CliConfirmGate:
        return CliConfirmGate(
            front.name.capitalize(),
            settings.limits.confirm_timeout_s,
            stdin.answers,
            out,
            lock=confirm_lock,
        )

    runtime = await build_chat_runtime(
        options.runtime,
        gate_factory,
        conversation_factory,
        manager_factory,
        runner_factory,
        watch,
        err=out or sys.stderr,
    )
    async with AsyncExitStack() as stack:
        stack.push_async_callback(runtime.aclose)
        channel = CliChannel(
            runtime.worker.name.capitalize(),
            stdin.answers,
            runtime.orchestrator.confirm,
            runtime.settings.limits.confirm_timeout_s,
            out,
            stdout,
            lock=confirm_lock,
        )
        conversation_id = select_conversation(runtime.memory, options.new_conversation)
        session = await runtime.open_session(conversation_id, channel)
        # The watcher stops before the session closes so no reload lands on a closed pool.
        repl = ChatRepl(
            session,
            stdin,
            runtime.memory,
            runtime.settings,
            out,
            stdout,
            before_close=runtime.watcher.stop,
        )
        return await repl.run()
