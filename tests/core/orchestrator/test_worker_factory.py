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
from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.cancel import CancelToken


def spec(role: str = "worker", name: str = "viernes") -> AgentSpec:
    return AgentSpec(
        name=name, role=role, model="claude-sonnet", path=Path("/tmp/x"), secrets=["supersecreto"]
    )


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.handlers: list = []
        self.managers: list[FakeManager] = []

    def runner_factory(self, settings, task_id, gate, call, cancel_token, handlers=None):
        self.calls.append((settings, task_id, gate, call, cancel_token))
        self.handlers.append(handlers)
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
    settings = load_settings(None)
    factory_settings: list = []

    def manager_factory(received):
        factory_settings.append(received)
        return manager

    factory = SdkWorkerFactory(
        settings,
        spec(),
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=manager_factory,
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
    assert factory_settings == [settings]


async def test_close_gives_up_on_a_manager_that_never_stops(tmp_path: Path) -> None:
    class HangingManager(FakeManager):
        async def stop(self) -> None:
            await asyncio.Event().wait()

    factory = SdkWorkerFactory(
        load_settings(None),
        spec(),
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=lambda settings: HangingManager(),
        runner_factory=Recorder().runner_factory,
        close_budget_s=0.05,
    )
    await factory.build_worker(
        Task("t1", TaskRequest(objetivo="a")), ListEventSink(), CancelToken(), AutoConfirmGate(True)
    )

    await asyncio.wait_for(factory.close(), 1)


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


# --- generations, subagents and native handlers ------------------------------------------------

from tests.core.runner_helpers import mcp_tool  # noqa: E402
from tony.core.loader import StdioServer, ToolConfig  # noqa: E402
from tony.core.mcp import ToolCatalog  # noqa: E402
from tony.core.skills import SkillSpec  # noqa: E402
from tony.core.subagents.launcher import NO_HOST_ERROR  # noqa: E402

CHILD = AgentSpec(
    name="investigador",
    role="worker",
    model="claude-sonnet",
    path=Path("/tmp/x/i"),
    parent="viernes",
)


def full_spec(native: list[str], skills: list[SkillSpec] | None = None) -> AgentSpec:
    return AgentSpec(
        name="viernes",
        role="worker",
        model="claude-sonnet",
        path=Path("/tmp/x"),
        tools=ToolConfig(mcpServers={"fs": StdioServer(command="fs")}, native=native),
        skills=skills or [],
        subagents={"investigador": CHILD},
    )


def make_full_factory(tmp_path: Path, spec: AgentSpec) -> tuple[SdkWorkerFactory, Recorder]:
    recorder = Recorder()
    recorder.manager_factory = lambda settings: _catalog_manager(recorder)  # type: ignore[method-assign]
    factory = SdkWorkerFactory(
        load_settings(None),
        spec,
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=recorder.manager_factory,
        runner_factory=recorder.runner_factory,
    )
    return factory, recorder


def _catalog_manager(recorder: Recorder) -> FakeManager:
    manager = FakeManager(ToolCatalog.build({"fs": [mcp_tool("read_file")]}, None, []))
    recorder.managers.append(manager)
    return manager


async def build(factory: SdkWorkerFactory, task: Task):
    return await factory.build_worker(task, ListEventSink(), CancelToken(), AutoConfirmGate(True))


async def test_root_task_leases_the_current_generation_and_release_frees_it(tmp_path) -> None:
    factory, recorder = make_full_factory(tmp_path, full_spec([]))

    await build(factory, Task("t1", TaskRequest(objetivo="a")))
    assert factory.pool.current is not None and factory.pool.current.leases == 1

    await factory.release("t1")

    assert factory.pool.current.leases == 0
    await factory.release("t1")
    assert factory.pool.current.leases == 0
    await factory.close()
    assert recorder.managers[0].stopped is True


async def test_subtask_is_built_with_its_subagent_over_the_root_generation(tmp_path) -> None:
    factory, recorder = make_full_factory(tmp_path, full_spec(["read_skill", "run_subagent"]))
    await build(factory, Task("t1", TaskRequest(objetivo="a")))

    worker = await build(factory, Task("s1", TaskRequest(objetivo="b"), "t1", agent="investigador"))

    assert worker.spec is CHILD
    assert worker.catalog.qualified_names() == ["fs.read_file"]
    assert len(recorder.managers) == 1
    assert recorder.calls[1][1] == "s1" and recorder.calls[1][3] == recorder.managers[0].call
    assert not hasattr(recorder.handlers[1], "run_subagent")
    await factory.release("s1")
    await factory.release("t1")
    await factory.close()


async def test_subtask_of_an_unknown_subagent_or_parent_fails_to_build(tmp_path) -> None:
    factory, _ = make_full_factory(tmp_path, full_spec([]))
    await build(factory, Task("t1", TaskRequest(objetivo="a")))

    with pytest.raises(LookupError, match="nadie"):
        await build(factory, Task("s1", TaskRequest(objetivo="b"), "t1", agent="nadie"))
    with pytest.raises(LookupError, match="t9"):
        await build(factory, Task("s2", TaskRequest(objetivo="b"), "t9", agent="investigador"))
    await factory.close()


async def test_update_spec_is_seen_by_the_next_task(tmp_path) -> None:
    factory, recorder = make_full_factory(tmp_path, full_spec(["read_skill"]))
    skill = SkillSpec(name="nueva", description="d", body="cuerpo nuevo", path=Path("/s"))

    await build(factory, Task("t1", TaskRequest(objetivo="a")))
    factory.update_spec(full_spec(["read_skill"], skills=[skill]))
    worker = await build(factory, Task("t2", TaskRequest(objetivo="b")))

    assert worker.spec.skills == [skill]
    assert await recorder.handlers[1].read_skill("nueva") == "cuerpo nuevo"
    assert factory.pool.current.leases == 2
    await factory.close()


async def test_native_handlers_offer_read_skill_and_run_subagent_to_the_root_worker(
    tmp_path,
) -> None:
    factory, recorder = make_full_factory(tmp_path, full_spec(["read_skill", "run_subagent"]))

    await build(factory, Task("t1", TaskRequest(objetivo="a")))

    handlers = recorder.handlers[0]
    assert hasattr(handlers, "read_skill") and hasattr(handlers, "run_subagent")
    result = await handlers.run_subagent("investigador", TaskRequest(objetivo="x"))
    assert result.errores == [NO_HOST_ERROR]
    await factory.close()


async def test_attached_host_receives_the_subtasks_of_the_root_worker(tmp_path) -> None:
    class Host:
        def __init__(self) -> None:
            self.submitted: list[tuple[str, str, str]] = []

        def submit_subtask(self, parent_id, agent, request):
            self.submitted.append((parent_id, agent, request.objetivo))
            return Task("s1", request, parent_id, agent=agent)

        async def wait(self, task_id):
            return TaskResult(status="ok", resumen="hijo")

    factory, recorder = make_full_factory(tmp_path, full_spec(["run_subagent"]))
    host = Host()
    factory.attach_host(host)
    await build(factory, Task("t1", TaskRequest(objetivo="a")))

    result = await recorder.handlers[0].run_subagent("investigador", TaskRequest(objetivo="x"))

    assert result.resumen == "hijo"
    assert host.submitted == [("t1", "investigador", "x")]
    await factory.close()


# --- per-root snapshots, child leases and recursive secrets (review of change 03) ---------------

READ_ONLY_CHILD = AgentSpec(
    name="investigador",
    role="worker",
    model="claude-sonnet",
    path=Path("/tmp/x/i"),
    parent="viernes",
    tools=ToolConfig(allow=["fs.read_file"]),
    secrets=["childpassword123"],
)
UNRESTRICTED_CHILD = READ_ONLY_CHILD.model_copy(update={"tools": ToolConfig(), "secrets": []})


def spec_with_child(child: AgentSpec) -> AgentSpec:
    return full_spec([]).model_copy(update={"subagents": {"investigador": child}})


def make_rw_factory(tmp_path: Path, spec: AgentSpec) -> tuple[SdkWorkerFactory, Recorder]:
    recorder = Recorder()

    def manager_factory(settings) -> FakeManager:
        tools = {"fs": [mcp_tool("read_file"), mcp_tool("write_file")]}
        manager = FakeManager(ToolCatalog.build(tools, None, []))
        recorder.managers.append(manager)
        return manager

    factory = SdkWorkerFactory(
        load_settings(None),
        spec,
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=manager_factory,
        runner_factory=recorder.runner_factory,
    )
    return factory, recorder


async def test_child_of_an_old_root_keeps_the_permissions_snapshotted_at_build(tmp_path) -> None:
    factory, _ = make_rw_factory(tmp_path, spec_with_child(READ_ONLY_CHILD))
    await build(factory, Task("t1", TaskRequest(objetivo="a")))

    factory.update_spec(spec_with_child(UNRESTRICTED_CHILD))
    old_child = await build(
        factory, Task("s1", TaskRequest(objetivo="b"), "t1", agent="investigador")
    )
    await build(factory, Task("t2", TaskRequest(objetivo="c")))
    new_child = await build(
        factory, Task("s2", TaskRequest(objetivo="d"), "t2", agent="investigador")
    )

    assert old_child.catalog.qualified_names() == ["fs.read_file"]
    assert old_child.spec is READ_ONLY_CHILD
    assert sorted(new_child.catalog.qualified_names()) == ["fs.read_file", "fs.write_file"]
    await factory.close()


async def test_child_lease_keeps_a_retired_generation_until_the_child_is_released(
    tmp_path,
) -> None:
    factory, recorder = make_rw_factory(tmp_path, spec_with_child(READ_ONLY_CHILD))
    await build(factory, Task("t1", TaskRequest(objetivo="a")))
    await build(factory, Task("s1", TaskRequest(objetivo="b"), "t1", agent="investigador"))
    await factory.pool.swap(ToolConfig(mcpServers={"fs": StdioServer(command="fs2")}))

    await factory.release("t1")
    assert recorder.managers[0].stopped is False

    await factory.release("s1")
    assert recorder.managers[0].stopped is True
    assert recorder.managers[1].stopped is False
    await factory.close()


def test_subagent_secrets_are_redacted_from_logs_even_after_a_reload_drops_them(
    tmp_path,
) -> None:
    factory, _ = make_rw_factory(tmp_path, spec_with_child(READ_ONLY_CHILD))

    def logged_line(task_id: str) -> dict:
        log = factory.open_log(task_id)
        log.emit("x", {"a": "clave childpassword123 vista"})
        log.close()
        return json.loads(log.path.read_text().splitlines()[0])

    assert logged_line("t1")["payload"] == {"a": "clave *** vista"}
    factory.update_spec(spec_with_child(UNRESTRICTED_CHILD))
    assert logged_line("t2")["payload"] == {"a": "clave *** vista"}
