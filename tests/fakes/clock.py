"""Clock double: time only moves when the test says so."""

from __future__ import annotations

import asyncio

SETTLE_ROUNDS = 25


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def monotonic(self) -> float:
        return self._now

    @property
    def pending(self) -> int:
        return len(self._sleepers)

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        entry = (self._now + seconds, asyncio.get_running_loop().create_future())
        self._sleepers.append(entry)
        try:
            await entry[1]
        finally:
            if entry in self._sleepers:
                self._sleepers.remove(entry)

    async def advance(self, seconds: float) -> None:
        await self.settle()
        self._now += seconds
        for entry in [e for e in self._sleepers if e[0] <= self._now]:
            self._sleepers.remove(entry)
            if not entry[1].done():
                entry[1].set_result(None)
        await self.settle()

    async def settle(self) -> None:
        for _ in range(SETTLE_ROUNDS):
            await asyncio.sleep(0)
