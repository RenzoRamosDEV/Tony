"""Tests for the in-process MCP proxies (single execution barrier)."""

from __future__ import annotations

from typing import Any

from tests.core.runner_helpers import ECHO_SCHEMA, fake_catalog
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.mcp import ToolCallOutcome
from tony.core.runner.proxy import TaskState, ToolProxyFactory


class RecordingCaller:
    def __init__(self, outcome: ToolCallOutcome | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], float]] = []
        self.outcome = outcome or ToolCallOutcome(ok=True, content="hola", duration_ms=7)

    async def __call__(
        self, qualified: str, args: dict[str, Any], timeout: float
    ) -> ToolCallOutcome:
        self.calls.append((qualified, args, timeout))
        return self.outcome


class InterruptSpy:
    def __init__(self) -> None:
        self.count = 0

    async def __call__(self) -> None:
        self.count += 1


def make_factory(gate: AutoConfirmGate, caller: RecordingCaller, catalog=None):
    sink = ListEventSink()
    state = TaskState(task_id="t1")
    factory = ToolProxyFactory(
        fake_catalog() if catalog is None else catalog,
        call=caller,
        gate=gate,
        events=sink,
        task_state=state,
        tool_timeout_s=20,
        confirm_timeout_s=60,
    )
    return factory, sink, state


async def test_echo_proxy_emits_call_and_result_and_returns_content() -> None:
    caller = RecordingCaller()
    factory, sink, state = make_factory(AutoConfirmGate(True), caller)

    reply = await factory.handler("fake.echo")({"text": "hola"})

    assert reply == {"content": [{"type": "text", "text": "hola"}]}
    assert caller.calls == [("fake.echo", {"text": "hola"}, 20)]
    assert sink.events == [
        ("tool.call", {"tool": "fake.echo", "args": {"text": "hola"}}),
        ("tool.result", {"tool": "fake.echo", "ok": True, "duration_ms": 7, "error": None}),
    ]
    assert state.steps == ["fake.echo(hola)"]
    assert state.cancelled is False


async def test_failed_call_is_returned_as_error_result() -> None:
    caller = RecordingCaller(
        ToolCallOutcome.failure("timeout tras 20 s en fake.echo", duration_ms=20000)
    )
    factory, sink, _ = make_factory(AutoConfirmGate(True), caller)

    reply = await factory.handler("fake.echo")({"text": "x"})

    assert reply == {
        "content": [{"type": "text", "text": "timeout tras 20 s en fake.echo"}],
        "is_error": True,
    }
    assert sink.payloads("tool.result") == [
        {
            "tool": "fake.echo",
            "ok": False,
            "duration_ms": 20000,
            "error": "timeout tras 20 s en fake.echo",
        }
    ]


async def test_rejected_confirmation_cancels_task_and_interrupts() -> None:
    caller = RecordingCaller()
    gate = AutoConfirmGate(False)
    factory, sink, state = make_factory(gate, caller)
    spy = InterruptSpy()
    state.interrupt = spy

    reply = await factory.handler("fake.destroy")({})

    assert reply == {
        "content": [{"type": "text", "text": "Tool fake.destroy no confirmada por el usuario"}],
        "is_error": True,
    }
    assert caller.calls == []
    assert state.cancelled is True
    assert state.cancel_reason == "fake.destroy"
    assert spy.count == 1
    assert [r.tool for r in gate.requests] == ["fake.destroy"]
    assert gate.requests[0].task_id == "t1"
    assert sink.types() == ["tool.call", "tool.result"]
    assert sink.payloads("tool.result")[0]["ok"] is False
    assert "no confirmada" in sink.payloads("tool.result")[0]["error"]


async def test_approved_confirmation_executes_the_tool() -> None:
    caller = RecordingCaller()
    gate = AutoConfirmGate(True)
    factory, _, state = make_factory(gate, caller)

    await factory.handler("fake.destroy")({})

    assert len(gate.requests) == 1
    assert caller.calls == [("fake.destroy", {}, 20)]
    assert state.cancelled is False


async def test_tool_without_needs_confirm_never_asks_the_gate() -> None:
    gate = AutoConfirmGate(False)
    factory, _, state = make_factory(gate, RecordingCaller())

    await factory.handler("fake.echo")({"text": "x"})

    assert gate.requests == []
    assert state.cancelled is False


async def test_each_confirmation_request_is_fresh() -> None:
    gate = AutoConfirmGate(True)
    factory, _, _ = make_factory(gate, RecordingCaller())

    await factory.handler("fake.destroy")({})
    await factory.handler("fake.destroy")({})

    assert len(gate.requests) == 2
    assert gate.requests[0].confirmation_id != gate.requests[1].confirmation_id


async def test_confirmation_timeout_counts_as_rejection() -> None:
    class SlowGate:
        async def confirm(self, request):
            import asyncio

            await asyncio.sleep(1)
            return True

    sink = ListEventSink()
    state = TaskState(task_id="t1")
    factory = ToolProxyFactory(
        fake_catalog(),
        call=RecordingCaller(),
        gate=SlowGate(),
        events=sink,
        task_state=state,
        tool_timeout_s=20,
        confirm_timeout_s=0.05,
    )

    reply = await factory.handler("fake.destroy")({})

    assert reply["is_error"] is True
    assert state.cancelled is True


def test_sdk_servers_expose_original_name_description_and_schema() -> None:
    factory, _, _ = make_factory(AutoConfirmGate(True), RecordingCaller())

    servers = factory.build()

    assert list(servers) == ["fake"]
    assert servers["fake"]["type"] == "sdk"
    assert servers["fake"]["name"] == "fake"
    tools = {tool.name: tool for tool in factory.sdk_tools["fake"]}
    assert set(tools) == {"echo", "destroy"}
    assert tools["echo"].description == "desc echo"
    assert tools["echo"].input_schema == ECHO_SCHEMA
    assert tools["destroy"].annotations.destructive_hint is True


def test_catalog_filtered_by_allow_builds_only_allowed_proxies() -> None:
    factory, _, _ = make_factory(
        AutoConfirmGate(True), RecordingCaller(), catalog=fake_catalog(allow=["fake.echo"])
    )

    factory.build()

    assert [t.name for t in factory.sdk_tools["fake"]] == ["echo"]


def test_empty_catalog_builds_no_servers() -> None:
    factory, _, _ = make_factory(
        AutoConfirmGate(True), RecordingCaller(), catalog=fake_catalog(allow=[])
    )

    assert factory.build() == {}


async def test_rejected_confirmation_result_payload_is_exact() -> None:
    gate = AutoConfirmGate(False)
    factory, sink, _ = make_factory(gate, RecordingCaller())

    await factory.handler("fake.destroy")({"path": "a.md", "force": True})

    assert sink.payloads("tool.result") == [
        {
            "tool": "fake.destroy",
            "ok": False,
            "duration_ms": 0,
            "error": "Tool fake.destroy no confirmada por el usuario",
        }
    ]
    assert gate.requests[0].args_normalized == '{"force": true, "path": "a.md"}'


async def test_failed_outcome_without_message_uses_generic_error() -> None:
    caller = RecordingCaller(ToolCallOutcome(ok=False, error=None, duration_ms=3))
    factory, _, _ = make_factory(AutoConfirmGate(True), caller)

    reply = await factory.handler("fake.echo")({"text": "x"})

    assert reply == {"content": [{"type": "text", "text": "error desconocido"}], "is_error": True}


async def test_step_description_joins_argument_values() -> None:
    factory, _, state = make_factory(AutoConfirmGate(True), RecordingCaller())

    await factory.handler("fake.echo")({"text": "a", "n": 2})

    assert state.steps == ["fake.echo(a, 2)"]


def test_only_destructive_proxies_carry_annotations() -> None:
    factory, _, _ = make_factory(AutoConfirmGate(True), RecordingCaller())

    tools = {tool.name: tool for tool in factory.sdk_tools["fake"]}

    assert tools["echo"].annotations is None
    assert tools["destroy"].annotations.destructive_hint is True
