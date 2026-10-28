"""StdinReader: daemon-thread line pump behind a cancellable asyncio readline."""

from __future__ import annotations

import asyncio
import os
import threading
import time

from tony.apps.cli.stdin_reader import StdinReader


async def test_readline_returns_each_line_typed_during_a_read_then_eof() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))

    first = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"a\n")
    assert await asyncio.wait_for(first, 1) == "a\n"
    second = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"b\n")
    assert await asyncio.wait_for(second, 1) == "b\n"
    os.close(write_end)
    assert await asyncio.wait_for(reader.readline(), 1) is None
    assert await reader.readline() is None


async def test_readline_is_cancellable_while_stdin_is_blocked() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))
    pending = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)

    pending.cancel()
    started = time.monotonic()
    try:
        await pending
    except asyncio.CancelledError:
        pass

    assert time.monotonic() - started < 1
    os.close(write_end)


def test_a_blocked_reader_does_not_keep_the_process_alive() -> None:
    read_end, write_end = os.pipe()

    async def scenario() -> None:
        reader = StdinReader(os.fdopen(read_end, "r"))
        pending = asyncio.ensure_future(reader.readline())
        await asyncio.sleep(0.05)
        pending.cancel()

    started = time.monotonic()
    asyncio.run(scenario())

    pump = [t for t in threading.enumerate() if t.name == "tony-stdin"]
    assert pump and all(t.daemon for t in pump)
    assert time.monotonic() - started < 2
    os.close(write_end)


async def test_late_answer_to_an_abandoned_read_is_discarded() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))
    pending = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    os.write(write_end, b"tarde\n")
    await asyncio.sleep(0.05)

    fresh = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"nueva\n")

    assert await asyncio.wait_for(fresh, 1) == "nueva\n"
    os.close(write_end)


async def test_answer_typed_after_the_new_read_started_is_accepted() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))
    pending = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)

    fresh = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"s\n")

    assert await asyncio.wait_for(fresh, 1) == "s\n"
    os.close(write_end)


async def test_lines_typed_before_the_read_started_are_discarded_even_if_queued() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))
    pending = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    os.write(write_end, b"s\n")
    os.write(write_end, b"otra\n")
    await asyncio.sleep(0.05)

    fresh = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"nueva\n")

    assert await asyncio.wait_for(fresh, 1) == "nueva\n"
    os.close(write_end)


async def test_eof_is_honoured_even_when_it_arrived_before_the_read() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))
    pending = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    os.close(write_end)
    await asyncio.sleep(0.05)

    assert await asyncio.wait_for(reader.readline(), 1) is None


async def test_a_line_typed_while_nobody_was_reading_never_answers_the_next_read() -> None:
    read_end, write_end = os.pipe()
    reader = StdinReader(os.fdopen(read_end, "r"))
    first = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"hola\n")
    assert await asyncio.wait_for(first, 1) == "hola\n"
    os.write(write_end, b"s\n")
    await asyncio.sleep(0.05)

    fresh = asyncio.ensure_future(reader.readline())
    await asyncio.sleep(0.05)
    os.write(write_end, b"nueva\n")

    assert await asyncio.wait_for(fresh, 1) == "nueva\n"
    os.close(write_end)
