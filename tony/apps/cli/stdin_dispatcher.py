"""Routes stdin lines while a turn runs: /cancel, confirmation answers, or a busy notice."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import TextIO

from tony.apps.cli.stdin_reader import LineSource

BUSY_NOTICE = "Espera a que termine la tarea.\n"
CANCEL_COMMAND = "/cancel"


class AnswerSource:
    """LineSource for confirmation prompts: fed by the dispatcher, never by stdin directly."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.pending = 0

    async def readline(self) -> str | None:
        self.pending += 1
        try:
            return await self._queue.get()
        finally:
            self.pending -= 1

    def feed(self, line: str | None) -> None:
        self._queue.put_nowait(line)


class StdinDispatcher:
    """Owns stdin: prompts read it directly; during a turn every line is dispatched."""

    def __init__(self, lines: LineSource, out: TextIO | None = None) -> None:
        self._lines = lines
        self._out = out
        self.answers = AnswerSource()
        self._leftover: str | None = None
        self._eof = False

    async def readline(self) -> str | None:
        if self._leftover is not None:
            line, self._leftover = self._leftover, None
            return line
        if self._eof:
            return None
        return await self._lines.readline()

    async def during[T](self, turn: Awaitable[T], on_cancel: Callable[[], Awaitable[None]]) -> T:
        task = asyncio.ensure_future(turn)
        read: asyncio.Future[str | None] | None = None
        try:
            while not task.done() and not self._eof:
                read = read or asyncio.ensure_future(self.readline())
                await asyncio.wait({task, read}, return_when=asyncio.FIRST_COMPLETED)
                if read.done():
                    line, read = read.result(), None
                    await self._dispatch(line, task.done(), on_cancel)
            return await task
        finally:
            for future in (task, read):
                if future is not None and not future.done():
                    future.cancel()
                    await asyncio.gather(future, return_exceptions=True)

    async def _dispatch(
        self, line: str | None, turn_done: bool, on_cancel: Callable[[], Awaitable[None]]
    ) -> None:
        if line is None:
            self._eof = True
            if self.answers.pending:
                self.answers.feed(None)
        elif self.answers.pending:
            self.answers.feed(line)
        elif turn_done:
            self._leftover = line
        elif line.strip() == CANCEL_COMMAND:
            await on_cancel()
        elif line.strip():
            self._err(BUSY_NOTICE)

    def _err(self, text: str) -> None:
        out = self._out or sys.stderr
        out.write(text)
        out.flush()
