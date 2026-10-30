"""ToolBarrier: the transport-agnostic cancel -> allow -> confirm -> timeout -> log logic.

`ToolProxyFactory` builds in-process SDK proxies for `claude_sdk`; a future stdio MCP
gateway for `codex_cli` needs the exact same cancellation/confirmation/timeout/logging
order without any `claude_agent_sdk` transport wiring. This module tests that logic in
isolation from `ToolProxyFactory`, and that `ToolProxyFactory` is built on top of it
rather than duplicating it.
"""

from __future__ import annotations

from typing import Any

from tests.core.runner_helpers import fake_catalog
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.mcp import ToolCallOutcome
from tony.core.runner.proxy import TaskState, ToolBarrier, ToolProxyFactory


class RecordingCaller:
    def __init__(self, outcome: ToolCallOutcome | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], float]] = []
        self.outcome = outcome or ToolCallOutcome(ok=True, content="hola", duration_ms=7)

    async def __call__(
        self, qualified: str, args: dict[str, Any], timeout: float
    ) -> ToolCallOutcome:
        self.calls.append((qualified, args, timeout))
        return self.outcome


def make_barrier(gate, caller, catalog=None):
    sink = ListEventSink()
    state = TaskState(task_id="t1")
    barrier = ToolBarrier(
        fake_catalog() if catalog is None else catalog,
        call=caller,
        gate=gate,
        events=sink,
        task_state=state,
        tool_timeout_s=20,
        confirm_timeout_s=60,
    )
    return barrier, sink, state


async def test_barrier_handler_executes_an_allowed_tool_without_sdk_wiring() -> None:
    """No `claude_agent_sdk` type is needed to drive a catalog's tools through the barrier."""
    caller = RecordingCaller()
    barrier, sink, state = make_barrier(AutoConfirmGate(True), caller)

    reply = await barrier.handler("fake.echo")({"text": "hola"})

    assert reply == {"content": [{"type": "text", "text": "hola"}]}
    assert caller.calls == [("fake.echo", {"text": "hola"}, 20)]
    assert sink.events == [
        ("tool.call", {"tool": "fake.echo", "args": {"text": "hola"}}),
        ("tool.result", {"tool": "fake.echo", "ok": True, "duration_ms": 7, "error": None}),
    ]
    assert state.steps == ["fake.echo(hola)"]


async def test_barrier_rejects_unconfirmed_destructive_tool_and_cancels() -> None:
    caller = RecordingCaller()
    barrier, _, state = make_barrier(AutoConfirmGate(False), caller)

    reply = await barrier.handler("fake.destroy")({})

    assert reply["is_error"] is True
    assert "no confirmada" in reply["content"][0]["text"]
    assert caller.calls == []
    assert state.cancelled is True


async def test_barrier_rejects_calls_once_the_task_is_cancelled() -> None:
    caller = RecordingCaller()
    barrier, _, state = make_barrier(AutoConfirmGate(True), caller)
    state.cancel("fake.other")

    reply = await barrier.handler("fake.echo")({"text": "x"})

    assert reply["is_error"] is True
    assert "cancelada" in reply["content"][0]["text"]
    assert caller.calls == []


async def test_barrier_confirmation_timeout_counts_as_rejection() -> None:
    class SlowGate:
        async def confirm(self, request):
            import asyncio

            await asyncio.sleep(1)
            return True

    barrier, _, state = make_barrier(SlowGate(), RecordingCaller())
    barrier._confirm_timeout_s = 0.05

    reply = await barrier.handler("fake.destroy")({})

    assert reply["is_error"] is True
    assert state.cancelled is True


async def test_tool_proxy_factory_delegates_every_call_to_a_tool_barrier() -> None:
    """`ToolProxyFactory` is the SDK-transport adapter on top of `ToolBarrier`, not a copy."""
    caller = RecordingCaller()
    sink = ListEventSink()
    state = TaskState(task_id="t1")
    factory = ToolProxyFactory(
        fake_catalog(),
        call=caller,
        gate=AutoConfirmGate(True),
        events=sink,
        task_state=state,
        tool_timeout_s=20,
        confirm_timeout_s=60,
    )

    assert isinstance(factory.barrier, ToolBarrier)
    assert factory.handler("fake.echo") is factory.barrier.handler("fake.echo")
