"""Tests for the in-process MCP proxies (single execution barrier)."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.types import CallToolRequestParams, PaginatedRequestParams

from tests.core.runner_helpers import ECHO_SCHEMA, fake_catalog, mcp_tool
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.mcp import ToolCallOutcome, ToolCatalog
from tony.core.runner.cancel import CancelToken
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


async def test_cancelled_task_rejects_further_tool_calls_without_executing() -> None:
    caller = RecordingCaller()
    factory, sink, state = make_factory(AutoConfirmGate(False), caller)
    await factory.handler("fake.destroy")({})

    reply = await factory.handler("fake.echo")({"text": "x"})

    assert reply == {
        "content": [{"type": "text", "text": "Tarea cancelada; no se ejecuta fake.echo"}],
        "is_error": True,
    }
    assert caller.calls == []
    assert sink.payloads("tool.result")[-1] == {
        "tool": "fake.echo",
        "ok": False,
        "duration_ms": 0,
        "error": "Tarea cancelada; no se ejecuta fake.echo",
    }


async def test_cancellation_during_confirmation_blocks_the_approved_call() -> None:
    caller = RecordingCaller()
    sink = ListEventSink()
    state = TaskState(task_id="t1")

    class CancellingGate:
        async def confirm(self, request) -> bool:
            state.cancel("fake.other")
            return True

    factory = ToolProxyFactory(
        fake_catalog(),
        call=caller,
        gate=CancellingGate(),
        events=sink,
        task_state=state,
        tool_timeout_s=20,
        confirm_timeout_s=60,
    )

    reply = await factory.handler("fake.destroy")({})

    assert reply == {
        "content": [{"type": "text", "text": "Tarea cancelada; no se ejecuta fake.destroy"}],
        "is_error": True,
    }
    assert caller.calls == []
    assert state.cancel_reason == "fake.other"
    assert sink.payloads("tool.result") == [
        {
            "tool": "fake.destroy",
            "ok": False,
            "duration_ms": 0,
            "error": "Tarea cancelada; no se ejecuta fake.destroy",
        }
    ]


async def server_handlers(factory: ToolProxyFactory, server: str):
    # The SDK registers plain handlers on an mcp Server; calling them is the in-process
    # equivalent of tools/list and tools/call without spinning up a transport.
    instance = factory.build()[server]["instance"]
    handlers = instance._request_handlers
    return handlers["tools/list"].handler, handlers["tools/call"].handler


@pytest.mark.parametrize(
    ("schema", "listed"),
    [
        ({"type": "object"}, {"type": "object", "properties": {}}),
        (
            {"type": "object", "additionalProperties": False},
            {"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ],
)
async def test_object_schema_without_properties_is_listed_and_callable(schema, listed) -> None:
    catalog = ToolCatalog.build({"fake": [mcp_tool("bare", schema=schema)]}, None, [])
    factory, _, _ = make_factory(AutoConfirmGate(True), RecordingCaller(), catalog=catalog)
    list_tools, call_tool = await server_handlers(factory, "fake")

    tools = (await list_tools(None, PaginatedRequestParams())).tools
    result = await call_tool(None, CallToolRequestParams(name="bare", arguments={}))

    assert [tool.input_schema for tool in tools] == [listed]
    assert result.is_error is False


async def test_cancelled_task_blocks_the_tool_before_allow_and_confirmation() -> None:
    caller = RecordingCaller()
    gate = AutoConfirmGate(True)
    factory, sink, state = make_factory(gate, caller)
    state.cancel_token.cancel("user")

    reply = await factory.handler("fake.destroy")({})

    assert reply == {
        "content": [{"type": "text", "text": "Tarea cancelada; no se ejecuta fake.destroy"}],
        "is_error": True,
    }
    assert caller.calls == []
    assert gate.requests == []
    assert sink.types() == ["tool.call", "tool.result"]
    assert sink.payloads("tool.result")[0]["ok"] is False


async def test_task_state_cancellation_is_visible_through_the_shared_token() -> None:
    token = CancelToken()
    state = TaskState(task_id="t1", cancel_token=token)

    state.cancel("fake.destroy")

    assert token.cancelled is True
    assert token.reason == "not_confirmed"
    assert state.cancelled is True
    assert state.cancel_reason == "fake.destroy"


async def test_external_cancellation_leaves_no_unconfirmed_tool() -> None:
    state = TaskState(task_id="t1")

    state.cancel_token.cancel("user")

    assert state.cancelled is True
    assert state.cancel_reason is None


async def test_interrupt_is_requested_at_most_once() -> None:
    state = TaskState(task_id="t1")
    spy = InterruptSpy()
    state.interrupt = spy

    await state.request_interrupt()
    await state.request_interrupt()

    assert spy.count == 1


async def test_proxies_consult_the_state_provider_on_every_call() -> None:
    caller = RecordingCaller()
    current = [TaskState(task_id="front")]
    current[0].cancel_token.cancel("user")
    factory = ToolProxyFactory(
        fake_catalog(),
        call=caller,
        gate=AutoConfirmGate(True),
        events=ListEventSink(),
        task_state=lambda: current[0],
        tool_timeout_s=20,
        confirm_timeout_s=60,
    )

    rejected = await factory.handler("fake.echo")({"text": "a"})
    current[0] = TaskState(task_id="front")
    executed = await factory.handler("fake.echo")({"text": "b"})

    assert rejected["is_error"] is True
    assert executed == {"content": [{"type": "text", "text": "hola"}]}
    assert caller.calls == [("fake.echo", {"text": "b"}, 20)]
    assert current[0].steps == ["fake.echo(b)"]
