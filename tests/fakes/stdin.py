"""LineSource double: scripted lines, None for EOF, a float pauses, blocks when exhausted."""

from __future__ import annotations

import asyncio

Item = str | float | None


class FakeStdin:
    def __init__(self, lines: list[Item] | None = None) -> None:
        self._queue: asyncio.Queue[Item] = asyncio.Queue()
        for line in lines or []:
            self._queue.put_nowait(line)

    def feed(self, line: Item) -> None:
        self._queue.put_nowait(line)

    async def readline(self) -> str | None:
        while True:
            item = await self._queue.get()
            if isinstance(item, float):
                await asyncio.sleep(item)
                continue
            return item
