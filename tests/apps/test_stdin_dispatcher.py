"""StdinDispatcher: stdin lines routed while a turn runs (specs/cli-chat: /cancel en curso)."""

from __future__ import annotations

import asyncio
import io

import pytest

from tests.fakes.stdin import FakeStdin
from tony.apps.cli.stdin_dispatcher import BUSY_NOTICE, StdinDispatcher


def make(lines: list) -> tuple[StdinDispatcher, FakeStdin, io.StringIO]:
    stdin, err = FakeStdin(lines), io.StringIO()
    return StdinDispatcher(stdin, err), stdin, err


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_cancel_line_during_a_turn_calls_on_cancel() -> None:
    dispatcher, stdin, _ = make([])
    cancelled = asyncio.Event()

    async def on_cancel() -> None:
        cancelled.set()

    async def turn() -> str:
        await cancelled.wait()
        return "done"

    running = asyncio.ensure_future(dispatcher.during(turn(), on_cancel))
    await settle()
    stdin.feed("/cancel\n")

    assert await asyncio.wait_for(running, 1) == "done"


async def test_line_during_a_pending_confirmation_is_its_answer() -> None:
    dispatcher, stdin, err = make([])

    async def turn() -> str | None:
        return await dispatcher.answers.readline()

    running = asyncio.ensure_future(dispatcher.during(turn(), _never))
    await settle()
    stdin.feed("s\n")

    assert await asyncio.wait_for(running, 1) == "s\n"
    assert err.getvalue() == ""


async def test_other_lines_during_a_turn_are_refused_and_blank_lines_ignored() -> None:
    dispatcher, stdin, err = make([])
    finish = asyncio.Event()

    async def turn() -> str:
        await finish.wait()
        return "ok"

    running = asyncio.ensure_future(dispatcher.during(turn(), _never))
    await settle()
    stdin.feed("hola\n")
    stdin.feed("\n")
    await settle()
    finish.set()

    assert await asyncio.wait_for(running, 1) == "ok"
    assert err.getvalue() == BUSY_NOTICE


async def test_line_arriving_as_the_turn_finishes_is_kept_for_the_prompt() -> None:
    dispatcher, _, err = make(["/salir\n"])

    async def turn() -> str:
        return "instant"

    assert await dispatcher.during(turn(), _never) == "instant"
    assert await asyncio.wait_for(dispatcher.readline(), 1) == "/salir\n"
    assert err.getvalue() == ""


async def test_eof_during_a_turn_rejects_the_pending_answer_and_ends_input() -> None:
    dispatcher, stdin, _ = make([])

    async def turn() -> str | None:
        return await dispatcher.answers.readline()

    running = asyncio.ensure_future(dispatcher.during(turn(), _never))
    await settle()
    stdin.feed(None)

    assert await asyncio.wait_for(running, 1) is None
    assert await asyncio.wait_for(dispatcher.readline(), 1) is None


async def test_cancelling_the_supervision_cancels_the_turn_too() -> None:
    dispatcher, _, _ = make([])
    turn_cancelled = asyncio.Event()

    async def turn() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            turn_cancelled.set()
            raise

    running = asyncio.ensure_future(dispatcher.during(turn(), _never))
    await settle()
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)

    assert turn_cancelled.is_set()


async def test_turn_exception_propagates() -> None:
    dispatcher, _, _ = make([])

    async def turn() -> None:
        raise ConnectionError("cli died")

    with pytest.raises(ConnectionError):
        await dispatcher.during(turn(), _never)


async def _never() -> None:
    raise AssertionError("on_cancel must not be called")
