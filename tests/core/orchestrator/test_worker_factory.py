"""SdkWorkerFactory: shared MCP manager started lazily, one runner per task."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.apps.cli_helpers import FakeManager
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.config import load_settings
from tony.core.loader import AgentSpec
from tony.core.mcp import McpServerStatus
from tony.core.orchestrator.task import Task
from tony.core.orchestrator.worker import SdkWorkerFactory, role_mismatch_warning
from tony.core.runner import TaskRequest
from tony.core.runner.cancel import CancelToken


def spec(role: str = "worker", name: str = "viernes") -> AgentSpec:
    return AgentSpec(
        name=name, role=role, model="claude-sonnet", path=Path("/tmp/x"), secrets=["supersecreto"]
    )


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.managers: list[FakeManager] = []

    def runner_factory(self, settings, task_id, gate, call, cancel_token):
        self.calls.append((settings, task_id, gate, call, cancel_token))
        return object()

    def manager_factory(self, settings):
        manager = FakeManager()
        manager.statuses = {"fs": McpServerStatus("fs", "ready", None, 2, None)}
        self.managers.append(manager)
        return manager


def make_factory(tmp_path: Path) -> tuple[SdkWorkerFactory, Recorder]:
    recorder = Recorder()
    factory = SdkWorkerFactory(
        load_settings(None),
        spec(),
        logs_dir=tmp_path / "logs",
        secrets=["dotenvsecret"],
        manager_factory=recorder.manager_factory,
        runner_factory=recorder.runner_factory,
    )
    return factory, recorder


def test_open_log_writes_a_jsonl_per_task_with_redaction(tmp_path: Path) -> None:
    factory, _ = make_factory(tmp_path)

    log = factory.open_log("t1")
    log.emit("x", {"a": "supersecreto y dotenvsecret"})
    log.close()

    assert log.path.parent.parent == tmp_path / "logs"
    assert log.path.name == "t1.jsonl"
    line = json.loads(log.path.read_text().splitlines()[0])
    assert line["payload"] == {"a": "*** y ***"}


async def test_manager_starts_once_and_each_task_gets_its_own_runner(tmp_path: Path) -> None:
    factory, recorder = make_factory(tmp_path)
    events = ListEventSink()
    token, gate = CancelToken(), AutoConfirmGate(True)

    first = await factory.build_worker(Task("t1", TaskRequest(objetivo="a")), events, token, gate)
    second = await factory.build_worker(
        Task("t2", TaskRequest(objetivo="b")), ListEventSink(), CancelToken(), gate
    )

    assert len(recorder.managers) == 1
    manager = recorder.managers[0]
    assert manager.started_with == spec().tools
    assert first.spec == spec()
    assert first.catalog is manager.catalog
    assert first.runner is not second.runner
    assert recorder.calls[0][1:] == ("t1", gate, manager.call, token)
    assert events.payloads("mcp.status") == [
        {"fs": {"state": "ready", "error": None, "tool_count": 2}}
    ]


async def test_close_stops_the_manager_only_if_it_was_started(tmp_path: Path) -> None:
    factory, recorder = make_factory(tmp_path)

    await factory.close()
    assert recorder.managers == []

    await factory.build_worker(
        Task("t1", TaskRequest(objetivo="a")), ListEventSink(), CancelToken(), AutoConfirmGate(True)
    )
    await factory.close()
    assert recorder.managers[0].stopped is True


def test_role_mismatch_warning_names_agent_and_both_roles() -> None:
    assert role_mismatch_warning(spec(role="front", name="jarvis"), "worker") == (
        "Aviso: el agente 'jarvis' tiene role 'front' pero se usa como 'worker'"
    )
    assert role_mismatch_warning(spec(), "worker") is None


def test_factory_exposes_its_role_warning(tmp_path: Path) -> None:
    recorder = Recorder()
    factory = SdkWorkerFactory(
        load_settings(None),
        spec(role="front", name="jarvis"),
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=recorder.manager_factory,
        runner_factory=recorder.runner_factory,
    )

    assert factory.warnings == [
        "Aviso: el agente 'jarvis' tiene role 'front' pero se usa como 'worker'"
    ]


class TaskRecordingManager(FakeManager):
    def __init__(self) -> None:
        super().__init__()
        self.started_in: asyncio.Task | None = None
        self.stopped_in: asyncio.Task | None = None

    async def start(self, tool_config, server_filter=None) -> None:
        self.started_in = asyncio.current_task()
        await super().start(tool_config, server_filter)

    async def stop(self) -> None:
        self.stopped_in = asyncio.current_task()
        await super().stop()


async def test_manager_is_started_and_stopped_by_the_same_task(tmp_path: Path) -> None:
    manager = TaskRecordingManager()
    factory = SdkWorkerFactory(
        load_settings(None),
        spec(),
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=lambda settings: manager,
        runner_factory=Recorder().runner_factory,
    )

    async def first_task() -> None:
        await factory.build_worker(
            Task("t1", TaskRequest(objetivo="a")),
            ListEventSink(),
            CancelToken(),
            AutoConfirmGate(True),
        )

    await asyncio.create_task(first_task())
    await asyncio.wait_for(factory.close(), 1)

    assert manager.stopped is True
    assert manager.started_in is not None
    assert manager.started_in is manager.stopped_in
    assert manager.started_in is not asyncio.current_task()


async def test_manager_start_failure_fails_the_build_and_leaves_nothing_to_close(
    tmp_path: Path,
) -> None:
    class BrokenManager(FakeManager):
        async def start(self, tool_config, server_filter=None) -> None:
            raise RuntimeError("npx missing")

    factory = SdkWorkerFactory(
        load_settings(None),
        spec(),
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=lambda settings: BrokenManager(),
        runner_factory=Recorder().runner_factory,
    )

    with pytest.raises(RuntimeError, match="npx missing"):
        await factory.build_worker(
            Task("t1", TaskRequest(objetivo="a")),
            ListEventSink(),
            CancelToken(),
            AutoConfirmGate(True),
        )
    await asyncio.wait_for(factory.close(), 1)
