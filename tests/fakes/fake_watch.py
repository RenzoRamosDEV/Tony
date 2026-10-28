"""Scripted stand-in for `watchfiles.awatch`: batches fed by the test, stops on the event."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

Change = tuple[Any, str]
Batch = set[Change]


class ScriptedWatch:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Batch] = asyncio.Queue()
        self.calls: list[dict[str, Any]] = []
        self.finished = False

    def feed(self, batch: Batch) -> None:
        self._queue.put_nowait(set(batch))

    async def __call__(
        self,
        *paths: Any,
        watch_filter: Callable[[Any, str], bool] | None = None,
        stop_event: asyncio.Event | None = None,
        **options: Any,
    ) -> AsyncIterator[Batch]:
        self.calls.append({"paths": paths, **options})
        try:
            while True:
                batch = await self._next_batch(stop_event)
                if batch is None:
                    return
                filtered = {c for c in batch if watch_filter is None or watch_filter(*c)}
                if filtered:
                    yield filtered
        finally:
            self.finished = True

    async def _next_batch(self, stop_event: asyncio.Event | None) -> Batch | None:
        getter = asyncio.ensure_future(self._queue.get())
        waiters = {getter}
        stopper = None
        if stop_event is not None:
            stopper = asyncio.ensure_future(stop_event.wait())
            waiters.add(stopper)
        done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for future in waiters:
            if future not in done:
                future.cancel()
        if getter in done:
            return getter.result()
        return None
