"""StdinReader: daemon-thread line pump behind a cancellable asyncio readline."""

from __future__ import annotations

import asyncio
import io
import os
import threading
import time

from tony.apps.cli.stdin_reader import StdinReader


async def test_readline_returns_the_queued_lines_then_eof() -> None:
    reader = StdinReader(io.StringIO("a\nb\n"))

    assert await reader.readline() == "a\n"
    assert await reader.readline() == "b\n"
    assert await reader.readline() is None
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
    os.write(write_end, b"nueva\n")

    assert await asyncio.wait_for(reader.readline(), 1) == "nueva\n"
    os.close(write_end)
