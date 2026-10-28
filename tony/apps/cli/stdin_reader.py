"""Lines from stdin pumped by one daemon thread, so waiting on them is cancellable."""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Protocol, TextIO


class LineSource(Protocol):
    async def readline(self) -> str | None:
        """Next line of input; None once it is exhausted."""
        ...


class StdinReader:
    """One daemon thread does the blocking reads; asyncio consumers wait on a queue.

    When a read is abandoned (a prompt timed out), the answer that arrives late belongs
    to that stale prompt: it is discarded before the next read. A daemon thread never
    keeps the interpreter alive after a timeout or a Ctrl+C.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream
        self._queue: asyncio.Queue[str | None] | None = None
        self._eof = False
        self._abandoned = False

    async def readline(self) -> str | None:
        if self._eof:
            return None
        queue = self._start_pump()
        if self._abandoned:
            self._abandoned = False
            while not queue.empty():
                if queue.get_nowait() is None:
                    return self._end()
        try:
            line = await queue.get()
        except asyncio.CancelledError:
            self._abandoned = True
            raise
        return self._end() if line is None else line

    def _end(self) -> None:
        self._eof = True
        return None

    def _start_pump(self) -> asyncio.Queue[str | None]:
        if self._queue is None:
            self._queue = asyncio.Queue()
            stream = self._stream or sys.stdin
            loop = asyncio.get_running_loop()
            threading.Thread(
                target=_pump, args=(stream, loop, self._queue), daemon=True, name="tony-stdin"
            ).start()
        return self._queue


def _pump(stream: TextIO, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    try:
        for line in iter(stream.readline, ""):
            loop.call_soon_threadsafe(queue.put_nowait, line)
        loop.call_soon_threadsafe(queue.put_nowait, None)
    except (RuntimeError, ValueError):
        # The loop or the stream was closed while the thread was blocked on stdin.
        pass
