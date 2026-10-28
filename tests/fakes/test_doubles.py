"""The test doubles satisfy the core ports."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.fakes.channels import ListChannel
from tests.fakes.clock import FakeClock
from tests.fakes.conversation import FakeConversationRunner
from tests.fakes.fake_runner import FakeAgentRunner
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.scripted_runner import ScriptedRunner
from tests.fakes.sinks import ListEventSink
from tests.fakes.stdin import FakeStdin
from tony.core.channels.ports import Channel, Notice
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmRequest, ToolCallOutcome, ToolCatalog
from tony.core.orchestrator.clock import Clock
from tony.core.runner import AgentRunner, EventSink, TaskRequest, TaskResult
from tony.core.runner.cancel import CancelToken
from tony.core.runner.conversation import ConversationRunner, FrontTurn

SPEC = AgentSpec(name="v", role="worker", model="claude-sonnet", path=Path("/tmp/v"))


def test_doubles_are_instances_of_the_ports() -> None:
    assert isinstance(ListEventSink(), EventSink)
    assert isinstance(FakeAgentRunner(TaskResult(status="ok", resumen="r")), AgentRunner)
    assert isinstance(ScriptedRunner("t1", []), AgentRunner)
    assert isinstance(FakeClock(), Clock)
    assert isinstance(ListChannel(), Channel)
    assert isinstance(FakeConversationRunner([]), ConversationRunner)


async def test_fake_runner_emits_started_scripted_and_finished() -> None:
    runner = FakeAgentRunner(
        TaskResult(status="ok", resumen="r"), events=[("tool.call", {"tool": "x"})]
    )
    sink = ListEventSink()

    result = await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), sink)

    assert result.status == "ok"
    assert sink.types() == ["task.started", "tool.call", "task.finished"]
    assert sink.payloads("task.finished")[0]["status"] == "ok"


async def test_auto_confirm_gate_records_and_answers() -> None:
    gate = AutoConfirmGate(False)
    request = ConfirmRequest.create("t", "fs.write_file", {})

    assert await gate.confirm(request) is False
    assert gate.requests == [request]


async def test_fake_clock_advance_wakes_due_sleepers_only() -> None:
    clock = FakeClock()
    woken: list[str] = []

    async def sleeper(name: str, seconds: float) -> None:
        await clock.sleep(seconds)
        woken.append(name)

    short = asyncio.ensure_future(sleeper("short", 3))
    long = asyncio.ensure_future(sleeper("long", 60))
    await asyncio.sleep(0)

    await clock.advance(3)

    assert woken == ["short"]
    assert clock.monotonic() == 3
    assert short.done() and not long.done()
    long.cancel()


async def test_fake_clock_sleep_zero_returns_without_advance() -> None:
    clock = FakeClock()

    await asyncio.wait_for(clock.sleep(0), 0.1)


async def test_fake_clock_cancelled_sleep_is_forgotten() -> None:
    clock = FakeClock()
    sleeper = asyncio.ensure_future(clock.sleep(5))
    await asyncio.sleep(0)
    sleeper.cancel()
    await asyncio.sleep(0)

    assert clock.pending == 0


async def echo_call(qualified: str, args: dict, timeout: float) -> ToolCallOutcome:
    return ToolCallOutcome(ok=True, content="hola", duration_ms=1)


async def test_scripted_runner_executes_tool_steps_and_returns_the_scripted_result() -> None:
    final = TaskResult(status="ok", resumen="hecho", pasos=["fake.echo(hola)"])
    runner = ScriptedRunner("t1", [("tool", "fake.echo", {"text": "hola"}), ("result", final)])
    runner.call = echo_call
    sink = ListEventSink()

    result = await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), sink)

    assert result == final
    assert sink.types() == ["task.started", "tool.call", "tool.result", "task.finished"]
    assert sink.payloads("tool.call") == [{"tool": "fake.echo", "args": {"text": "hola"}}]
    assert sink.payloads("tool.result")[0]["ok"] is True


async def test_scripted_runner_confirm_step_asks_the_gate_and_cancels_on_rejection() -> None:
    gate = AutoConfirmGate(False)
    runner = ScriptedRunner("t1", [("confirm", "fake.destroy", {}), ("tool", "fake.echo", {})])
    runner.gate = gate
    sink = ListEventSink()

    result = await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), sink)

    assert result.status == "cancelled"
    assert result.errores == ["Tool fake.destroy no confirmada por el usuario"]
    assert [r.tool for r in gate.requests] == ["fake.destroy"]
    assert gate.requests[0].task_id == "t1"
    assert sink.payloads("tool.call") == [{"tool": "fake.destroy", "args": {}}]
    assert runner.cancel_token.cancelled is True


async def test_scripted_runner_confirm_step_executes_when_approved() -> None:
    runner = ScriptedRunner("t1", [("confirm", "fake.destroy", {"p": 1})])
    runner.gate = AutoConfirmGate(True)
    runner.call = echo_call
    sink = ListEventSink()

    result = await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), sink)

    assert result.status == "ok"
    assert result.pasos == ["fake.destroy(1)"]
    assert sink.payloads("tool.result")[0]["ok"] is True


async def test_scripted_runner_checks_the_cancel_token_before_each_step() -> None:
    calls: list[str] = []

    async def recording_call(qualified: str, args: dict, timeout: float) -> ToolCallOutcome:
        calls.append(qualified)
        return ToolCallOutcome(ok=True, content="", duration_ms=1)

    token = CancelToken()
    runner = ScriptedRunner(
        "t1", [("tool", "fake.a", {}), ("tool", "fake.b", {})], cancel_token=token
    )
    runner.call = recording_call
    token.cancel("user")

    result = await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), ListEventSink())

    assert calls == []
    assert result.status == "cancelled"
    assert result.errores == ["cancelada por el usuario"]


async def test_scripted_runner_sleep_step_ends_early_when_cancelled() -> None:
    clock = FakeClock()
    token = CancelToken()
    runner = ScriptedRunner("t1", [("sleep", 100)], cancel_token=token, clock=clock)
    running = asyncio.ensure_future(
        runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), ListEventSink())
    )
    await asyncio.sleep(0)
    assert not running.done()

    token.cancel("user")
    result = await asyncio.wait_for(running, 1)

    assert result.status == "cancelled"
    assert runner.interrupted_by == "user"


async def test_scripted_runner_sleep_step_completes_when_the_clock_advances() -> None:
    clock = FakeClock()
    runner = ScriptedRunner("t1", [("sleep", 2)], clock=clock)
    running = asyncio.ensure_future(
        runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), ListEventSink())
    )
    await asyncio.sleep(0)

    await clock.advance(2)

    assert (await running).status == "ok"


async def test_scripted_runner_raise_step_raises() -> None:
    runner = ScriptedRunner("t1", [("raise", "boom")])

    try:
        await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), ListEventSink())
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")


async def test_fake_conversation_runner_returns_scripted_turns_and_can_delegate() -> None:
    class Handlers:
        def __init__(self) -> None:
            self.requests: list[TaskRequest] = []

        async def delegate(self, request: TaskRequest) -> TaskResult:
            self.requests.append(request)
            return TaskResult(status="ok", resumen="3 ficheros")

        async def remember(self, text: str) -> str:
            return text

        async def set_reply_mode(self, mode: str) -> str:
            return mode

    async def delegating_turn(prompt: str, handlers) -> dict:
        result = await handlers.delegate(TaskRequest(objetivo="lista"))
        return {"display_text": result.resumen, "speech_text": None}

    runner = FakeConversationRunner(
        ["Hola", delegating_turn, {"display_text": "x", "speech_text": "y"}]
    )
    handlers = Handlers()
    await runner.open(SPEC, ToolCatalog.empty(), handlers, ListEventSink())

    first = await runner.turn("p1")
    second = await runner.turn("p2")
    third = await runner.turn("p3")
    await runner.interrupt()
    await runner.close()

    assert first == FrontTurn(text="Hola", structured=None)
    assert second.structured == {"display_text": "3 ficheros", "speech_text": None}
    assert third.structured == {"display_text": "x", "speech_text": "y"}
    assert [r.objetivo for r in handlers.requests] == ["lista"]
    assert runner.prompts == ["p1", "p2", "p3"]
    assert runner.interrupts == 1
    assert runner.closed is True
    assert runner.session_id == "fake-session"


async def test_list_channel_accumulates_messages_by_type() -> None:
    channel = ListChannel()

    await channel.send(Notice(text="a"))
    await channel.send(Notice(text="b"))

    assert channel.messages == [Notice(text="a"), Notice(text="b")]
    assert channel.of_type(Notice) == [Notice(text="a"), Notice(text="b")]


async def test_fake_stdin_delivers_lines_then_blocks() -> None:
    stdin = FakeStdin(["s\n", "n\n"])

    assert await stdin.readline() == "s\n"
    assert await stdin.readline() == "n\n"
    try:
        await asyncio.wait_for(stdin.readline(), 0.05)
    except TimeoutError:
        pass
    else:
        raise AssertionError("an exhausted FakeStdin must block")


async def test_fake_stdin_none_means_eof_and_feed_adds_lines() -> None:
    stdin = FakeStdin([None])

    assert await stdin.readline() is None

    stdin.feed("x\n")
    assert await stdin.readline() == "x\n"


# --- doubles added for skills, subagents and hot reload ---------------------------------

import sys  # noqa: E402

from tests.fakes.fake_watch import ScriptedWatch  # noqa: E402
from tests.fakes.worker_factory import FakeWorkerFactory  # noqa: E402
from tony.core.loader import StdioServer, ToolConfig  # noqa: E402
from tony.core.mcp import McpManager  # noqa: E402
from tony.core.orchestrator.task import Task  # noqa: E402

FS_TOOLS = ["fail", "list_directory", "read_file", "search_files", "write_file"]


def fs_server(root: Path) -> ToolConfig:
    server = StdioServer(
        command=sys.executable, args=["-m", "tests.fakes.fake_filesystem_server", str(root)]
    )
    return ToolConfig(mcpServers={"filesystem": server})


async def test_fake_filesystem_server_exposes_five_tools_over_the_given_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("hola mundo", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nada", encoding="utf-8")
    manager = McpManager(connect_timeout_s=10)
    try:
        await manager.start(fs_server(tmp_path))

        assert sorted(ref.name for ref in manager.catalog) == FS_TOOLS
        assert manager.catalog.get("filesystem.write_file").destructive is True
        assert manager.catalog.get("filesystem.read_file").destructive is False
        listed = await manager.call("filesystem.list_directory", {"path": "."}, 5)
        assert listed.ok and "a.md" in listed.content and "b.txt" in listed.content
        read = await manager.call("filesystem.read_file", {"path": "a.md"}, 5)
        assert read.ok and "hola mundo" in read.content
        found = await manager.call("filesystem.search_files", {"query": "mundo"}, 5)
        assert found.ok and "a.md" in found.content and "b.txt" not in found.content
        written = await manager.call(
            "filesystem.write_file", {"path": "c.md", "content": "nuevo"}, 5
        )
        assert written.ok and (tmp_path / "c.md").read_text(encoding="utf-8") == "nuevo"
        failed = await manager.call("filesystem.fail", {}, 5)
        assert failed.ok is False and "fallo simulado" in (failed.error or "")
    finally:
        await manager.stop()


async def test_scripted_watch_applies_the_filter_and_stops_on_the_event() -> None:
    watch = ScriptedWatch()
    stop = asyncio.Event()
    received: list[set] = []

    async def consume() -> None:
        async for batch in watch(
            "agents", watch_filter=lambda change, path: path.endswith(".json"), stop_event=stop
        ):
            received.append(batch)

    consumer = asyncio.ensure_future(consume())
    watch.feed({(2, "agents/v/tool/tool.json"), (2, "agents/v/agent.md")})
    watch.feed({(2, "agents/v/agent.md")})
    await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(consumer, 1)

    assert received == [{(2, "agents/v/tool/tool.json")}]
    assert watch.calls[0]["paths"] == ("agents",)


async def test_fake_worker_factory_records_host_logs_with_parent_and_releases() -> None:
    factory = FakeWorkerFactory(FakeClock())
    host = object()

    factory.attach_host(host)
    log = factory.open_log("s1", parent_id="t1")
    await factory.release("s1")
    await factory.build_worker(
        Task("t1", TaskRequest(objetivo="o")), ListEventSink(), CancelToken(), AutoConfirmGate(True)
    )

    assert factory.host is host
    assert factory.logs["s1"] is log and factory.parents == {"s1": "t1"}
    assert factory.released == ["s1"]
