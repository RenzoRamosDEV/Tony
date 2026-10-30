"""Shared CLI/web composition (design.md D2): settings, agents, memory, orchestrator, sessions."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.apps.cli_helpers import FakeManager, write_agent
from tests.fakes.channels import ListChannel
from tests.fakes.conversation import FakeConversationRunner
from tests.fakes.fake_watch import ScriptedWatch
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.scripted_runner import ScriptedRunner
from tony.core.channels.bootstrap import ChatError, ChatRuntime, RuntimeOptions, build_chat_runtime
from tony.core.channels.ports import Notice, TaskEvent
from tony.core.channels.session import ChatSession
from tony.core.orchestrator.orchestrator import Orchestrator
from tony.core.orchestrator.worker import SdkWorkerFactory
from tony.core.runner import TaskRequest


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


FAKE_SERVER = {"command": "python", "args": ["-m", "tests.fakes.fake_mcp_server"]}
MODIFIED = 2


def write_front(agents_dir: Path, name: str = "jarvis") -> None:
    write_agent(agents_dir, name, "front", model="claude-haiku")
    tool_dir = agents_dir / name / "tool"
    tool_dir.mkdir(exist_ok=True)
    (tool_dir / "tool.json").write_text(
        json.dumps({"native": ["delegate", "remember", "set_reply_mode"]}), encoding="utf-8"
    )


class Doubles:
    def __init__(self, tmp_path: Path, turns: list | None = None) -> None:
        self.root = tmp_path
        self.turns = turns or []
        self.runner = FakeConversationRunner(self.turns)
        self.managers: list[FakeManager] = []
        self.gate_calls: list[tuple[Any, Any]] = []
        self.watch = ScriptedWatch()
        self.scripts: dict[str, list] = {}
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "tony.yaml").write_text("", encoding="utf-8")
        write_front(tmp_path / "agents")
        write_agent(tmp_path / "agents", "viernes", "worker")

    def options(self) -> RuntimeOptions:
        return RuntimeOptions(
            config_path=self.root / "config" / "tony.yaml",
            agents_dir=self.root / "agents",
            logs_dir=self.root / "logs",
            memory_dir=self.root / "memory",
        )

    def manager_factory(self, settings) -> FakeManager:
        manager = FakeManager()
        self.managers.append(manager)
        return manager

    def runner_factory(self, settings, task_id, gate, call, token, handlers=None):
        return ScriptedRunner(task_id, self.scripts.get("x", []), cancel_token=token, gate=gate)

    def gate_factory(self, settings, front) -> AutoConfirmGate:
        self.gate_calls.append((settings, front))
        return AutoConfirmGate(True)

    async def build(self) -> ChatRuntime:
        return await build_chat_runtime(
            self.options(),
            gate_factory=self.gate_factory,
            conversation_factory=lambda settings, gate, call: self.runner,
            manager_factory=self.manager_factory,
            runner_factory=self.runner_factory,
            watch=self.watch,
        )


async def test_build_loads_settings_roles_memory_orchestrator_gate_and_watcher(tmp_path) -> None:
    d = Doubles(tmp_path)

    runtime = await d.build()

    assert (runtime.settings.front, runtime.front.name, runtime.worker.name) == (
        "jarvis",
        "jarvis",
        "viernes",
    )
    assert runtime.memory.conversations.path == tmp_path / "memory" / "conversations.sqlite"
    assert isinstance(runtime.orchestrator, Orchestrator)
    assert isinstance(runtime.worker_factory, SdkWorkerFactory)
    assert d.gate_calls == [(runtime.settings, runtime.front)]
    assert runtime.watcher.running is True
    await settle()
    assert d.watch.calls[0]["paths"] == (tmp_path / "agents",)
    assert runtime.warnings == [] and runtime.session is None
    await runtime.aclose()
    assert d.watch.finished is True


async def test_unoverridden_factories_resolve_to_the_claude_sdk_engine(tmp_path) -> None:
    """No `engine` declared anywhere: the selection point must pick the pre-existing plumbing."""
    from tony.core.runner.conversation import ClaudeSdkConversation
    from tony.core.runner.factory import default_worker_runner_factory

    d = Doubles(tmp_path)

    runtime = await build_chat_runtime(
        d.options(), gate_factory=d.gate_factory, manager_factory=d.manager_factory
    )

    assert runtime.worker_factory._runner_factory is default_worker_runner_factory
    assert isinstance(runtime.front_runner, ClaudeSdkConversation)
    await runtime.aclose()


async def test_open_session_starts_the_front_and_logs_the_session(tmp_path) -> None:
    d = Doubles(tmp_path, ["Hola."])
    runtime = await d.build()
    conversation = runtime.memory.conversations.start_conversation("web")

    session = await runtime.open_session(conversation, ListChannel())

    assert isinstance(session, ChatSession) and runtime.session is session
    assert session.conversation_id == conversation
    assert d.runner.opened == [runtime.front]
    await session.handle("hola")
    logs = list((tmp_path / "logs").glob(f"*/chat-{conversation}.jsonl"))
    assert len(logs) == 1
    assert json.loads(logs[0].read_text().splitlines()[0])["type"] == "session.started"
    await runtime.aclose()


async def test_close_session_closes_front_and_log_but_keeps_the_orchestrator(tmp_path) -> None:
    d = Doubles(tmp_path, ["a", "b"])
    runtime = await d.build()
    first = runtime.memory.conversations.start_conversation("web")
    session = await runtime.open_session(first, ListChannel())
    await session.handle("hola")
    log_path = runtime.session_log.path

    await runtime.close_session()

    assert d.runner.closed is True and runtime.session is None and runtime.session_log is None
    assert runtime.worker_factory.pool.current is None or d.managers == []
    second = runtime.memory.conversations.start_conversation("web")
    reopened = await runtime.open_session(second, ListChannel())
    assert reopened is not session and d.runner.opened == [runtime.front, runtime.front]
    result = await reopened.delegate(TaskRequest(objetivo="x"))
    assert result.status == "ok"
    assert log_path.exists() and runtime.session_log.path != log_path
    await runtime.aclose()


async def test_aclose_stops_everything_even_if_the_front_fails_to_close(tmp_path) -> None:
    d = Doubles(tmp_path, [])
    runtime = await d.build()
    conversation = runtime.memory.conversations.start_conversation("web")
    session = await runtime.open_session(conversation, ListChannel())
    await session.delegate(TaskRequest(objetivo="x"))

    async def broken_close() -> None:
        raise ConnectionError("front died")

    d.runner.close = broken_close  # type: ignore[method-assign]

    with pytest.raises(ConnectionError):
        await runtime.aclose()

    assert d.watch.finished is True
    assert all(m.stopped for m in d.managers) and len(d.managers) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        runtime.memory.conversations.has_conversation(conversation)


async def test_aclose_without_a_session_closes_memory_and_watcher(tmp_path) -> None:
    d = Doubles(tmp_path, [])
    runtime = await d.build()

    await runtime.aclose()

    assert d.watch.finished is True
    with pytest.raises(sqlite3.ProgrammingError):
        runtime.memory.conversations.list_conversations()


async def test_invalid_config_and_missing_agent_raise_chat_error_in_spanish(tmp_path) -> None:
    d = Doubles(tmp_path)
    (tmp_path / "config" / "tony.yaml").write_text("front: nadie\n", encoding="utf-8")
    with pytest.raises(ChatError, match="No existe el agente 'nadie'"):
        await d.build()

    (tmp_path / "config" / "tony.yaml").write_text("reply_mode: loud\n", encoding="utf-8")
    with pytest.raises(ChatError, match="Configuración inválida"):
        await d.build()


async def test_front_tools_start_a_manager_whose_catalog_reaches_the_session(tmp_path) -> None:
    d = Doubles(tmp_path, [])
    tool_json = tmp_path / "agents" / "jarvis" / "tool" / "tool.json"
    tool_json.write_text(
        json.dumps({"native": ["remember"], "mcpServers": {"fake": FAKE_SERVER}}),
        encoding="utf-8",
    )

    runtime = await d.build()

    assert len(d.managers) == 1 and d.managers[0].started_with is not None
    assert "fake" in d.managers[0].started_with.mcpServers
    assert runtime.front_manager is d.managers[0]
    await runtime.aclose()
    assert d.managers[0].stopped is True


async def test_reload_notice_reaches_the_open_session_as_notice_and_event(tmp_path) -> None:
    d = Doubles(tmp_path, [])
    runtime = await d.build()
    channel = ListChannel()
    await runtime.open_session(runtime.memory.conversations.start_conversation("web"), channel)
    tool = tmp_path / "agents" / "viernes" / "tool"
    tool.mkdir()
    path = tool / "tool.json"
    path.write_text(json.dumps({"mcpServers": {"fake": FAKE_SERVER}}), encoding="utf-8")

    d.watch.feed({(MODIFIED, str(path.resolve()))})
    for _ in range(50):
        if channel.of_type(TaskEvent):
            break
        await settle()

    notices = channel.of_type(Notice)
    assert len(notices) == 1 and "viernes" in notices[0].text and "recargada" in notices[0].text
    events = channel.of_type(TaskEvent)
    assert events[0].type == "config.reloaded" and events[0].task_id == "config"
    assert events[0].payload == {"agent": "viernes", "servers": ["fake"]}
    await runtime.aclose()
