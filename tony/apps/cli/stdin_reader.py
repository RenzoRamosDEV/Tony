"""Lines from stdin pumped by one daemon thread, so waiting on them is cancellable."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from typing import Protocol, TextIO


class LineSource(Protocol):
    async def readline(self) -> str | None:
        """Next line of input; None once it is exhausted."""
        ...


class StdinReader:
    """One daemon thread does the blocking reads; asyncio consumers wait on a queue.

    Every line is stamped when the thread read it. A read only accepts lines typed after it
    began: an answer to an abandoned prompt, or text typed while nobody was asking, can never
    answer a later question. A daemon thread never keeps the interpreter alive after a
    timeout or a Ctrl+C.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream
        self._queue: asyncio.Queue[tuple[float, str] | None] | None = None
        self._eof = False

    async def readline(self) -> str | None:
        if self._eof:
            return None
        started = time.monotonic()
        queue = self._start_pump()
        while True:
            item = await queue.get()
            if item is None:
                self._eof = True
                return None
            read_at, line = item
            if read_at >= started:
                return line

    def _start_pump(self) -> asyncio.Queue[tuple[float, str] | None]:
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
            loop.call_soon_threadsafe(queue.put_nowait, (time.monotonic(), line))
        loop.call_soon_threadsafe(queue.put_nowait, None)
    except (RuntimeError, ValueError):
        # The loop or the stream was closed while the thread was blocked on stdin.
        pass
