"""ConfirmationRouter and WebConfirmGate (design.md D7) with a FakeClock."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes.clock import FakeClock
from tony.apps.web.confirmations import ConfirmationRouter, InvalidConfirmation, WebConfirmGate
from tony.apps.web.protocol import ConversationStream
from tony.core.mcp import ConfirmRequest
from tony.core.orchestrator.errors import OrchestratorError

ARGS = {"source": "/n/a.md", "destination": "/n/.trash/a.md"}


class Resolver:
    def __init__(self, error: str | None = None) -> None:
        self.answers: list[bool] = []
        self.error = error

    async def __call__(self, approved: bool) -> None:
        self.answers.append(approved)
        if self.error:
            raise OrchestratorError(self.error)


def router(clock: FakeClock, timeout_s: float = 60) -> ConfirmationRouter:
    return ConfirmationRouter(now=clock.monotonic, timeout_s=timeout_s)


async def test_resolve_calls_the_resolver_once_and_retires_the_pending() -> None:
    clock, resolver = FakeClock(), Resolver()
    r = router(clock)
    r.register("a3f", "t-9", "filesystem.move_file", ARGS, resolver)

    await r.resolve("a3f", True)

    assert resolver.answers == [True]
    assert r.pending() is None
    with pytest.raises(InvalidConfirmation) as info:
        await r.resolve("a3f", False)
    assert info.value.code == "invalid_confirmation"
    assert resolver.answers == [True]


async def test_resolve_with_another_task_id_is_invalid_and_keeps_it_pending() -> None:
    clock, resolver = FakeClock(), Resolver()
    r = router(clock)
    r.register("a3f", "t-9", "filesystem.move_file", ARGS, resolver)

    with pytest.raises(InvalidConfirmation):
        await r.resolve("a3f", True, task_id="t-1")

    assert resolver.answers == []
    view = r.pending()
    assert view is not None and view.confirmation_id == "a3f"
    await r.resolve("a3f", False, task_id="t-9")
    assert resolver.answers == [False]


async def test_resolve_after_the_timeout_is_invalid() -> None:
    clock, resolver = FakeClock(), Resolver()
    r = router(clock)
    r.register("a3f", "t-9", "fs.write", {}, resolver)
    await clock.advance(60.5)

    with pytest.raises(InvalidConfirmation):
        await r.resolve("a3f", True)

    assert resolver.answers == [] and r.pending() is None


async def test_pending_view_reports_the_remaining_seconds() -> None:
    clock = FakeClock()
    r = router(clock)
    assert r.pending() is None
    r.register("a3f", "t-9", "filesystem.move_file", ARGS, Resolver())
    await clock.advance(20)

    view = r.pending()

    assert view is not None
    assert (view.confirmation_id, view.task_id, view.tool, view.args) == (
        "a3f",
        "t-9",
        "filesystem.move_file",
        ARGS,
    )
    assert view.expires_in_s == pytest.approx(40)
    await clock.advance(41)
    assert r.pending() is None


async def test_discard_task_retires_the_pending_of_that_task_only() -> None:
    clock = FakeClock()
    r = router(clock)
    r.register("a1", "t-1", "x", {}, Resolver())
    r.register("a2", "t-2", "y", {}, Resolver())

    r.discard_task("t-1")

    with pytest.raises(InvalidConfirmation):
        await r.resolve("a1", True)
    view = r.pending()
    assert view is not None and view.confirmation_id == "a2"
    r.discard_task("nobody")
    assert r.pending() is not None


async def test_resolver_orchestrator_error_becomes_invalid_confirmation() -> None:
    clock = FakeClock()
    r = router(clock)
    r.register("a3f", "t-9", "x", {}, Resolver(error="invalid_confirmation"))

    with pytest.raises(InvalidConfirmation) as info:
        await r.resolve("a3f", True)

    assert "invalid_confirmation" in info.value.detail
    assert r.pending() is None


def request() -> ConfirmRequest:
    return ConfirmRequest.create("front", "fake.destroy", ARGS)


async def test_front_gate_publishes_needs_confirmation_and_follows_the_resolution() -> None:
    clock = FakeClock()
    r = router(clock)
    stream = ConversationStream("c1")
    gate = WebConfirmGate(r, stream, timeout_s=60, clock=clock)
    req = request()

    asking = asyncio.ensure_future(gate.confirm(req))
    await clock.settle()
    published = stream.replay(0) or []
    assert len(published) == 1
    assert (published[0].type, published[0].task_id) == ("task.needs_confirmation", "front")
    assert published[0].payload == {
        "confirmation_id": req.confirmation_id,
        "tool": "fake.destroy",
        "args": ARGS,
        "expires_in_s": 60,
    }
    view = r.pending()
    assert view is not None and view.task_id == "front"
    assert (view.tool, view.args) == ("fake.destroy", ARGS)

    await r.resolve(req.confirmation_id, True)
    assert await asyncio.wait_for(asking, 1) is True
    confirmed = (stream.replay(0) or [])[1]
    assert (confirmed.type, confirmed.task_id) == ("task.confirmed", "front")
    assert confirmed.payload == {"confirmation_id": req.confirmation_id, "approved": True}


async def test_front_gate_rejection_returns_false() -> None:
    clock = FakeClock()
    r = router(clock)
    gate = WebConfirmGate(r, ConversationStream("c1"), timeout_s=60, clock=clock)
    req = request()

    asking = asyncio.ensure_future(gate.confirm(req))
    await clock.settle()
    await r.resolve(req.confirmation_id, False)

    assert await asyncio.wait_for(asking, 1) is False


async def test_front_gate_times_out_to_false_and_retires_the_pending() -> None:
    clock = FakeClock()
    r = router(clock)
    stream = ConversationStream("c1")
    gate = WebConfirmGate(r, stream, timeout_s=60, clock=clock)

    asking = asyncio.ensure_future(gate.confirm(request()))
    await clock.advance(59)
    assert not asking.done()
    await clock.advance(1)

    assert await asyncio.wait_for(asking, 1) is False
    assert r.pending() is None
    cancelled = (stream.replay(0) or [])[-1]
    assert (cancelled.type, cancelled.task_id) == ("task.cancelled", "front")
    assert cancelled.payload == {"reason": "not_confirmed"}
    assert clock.pending == 0


async def test_resolve_at_the_exact_deadline_is_still_valid() -> None:
    clock, resolver = FakeClock(), Resolver()
    r = router(clock)
    r.register("a3f", "t-9", "x", {}, resolver)
    await clock.advance(60)

    await r.resolve("a3f", True)

    assert resolver.answers == [True]


async def test_pending_reports_fractions_of_a_second() -> None:
    clock = FakeClock()
    r = router(clock)
    r.register("a3f", "t-9", "x", {}, Resolver())
    await clock.advance(59.5)

    view = r.pending()

    assert view is not None and view.expires_in_s == pytest.approx(0.5)


async def test_front_gate_without_a_stream_rejects() -> None:
    gate = WebConfirmGate(router(FakeClock()), None, timeout_s=60)

    assert await gate.confirm(request()) is False
