"""The dedicated thread pool where VAD, STT and TTS burn CPU without blocking the loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

MAX_WORKERS = 2
THREAD_NAME_PREFIX = "tony-voice"


class VoiceExecutor:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=THREAD_NAME_PREFIX
        )
        self._lanes: dict[str, asyncio.Lock] = {}

    async def run[T](self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, partial(fn, *args))

    async def run_serial[T](self, lane: str, fn: Callable[..., T], *args: Any) -> T:
        """Run one call at a time per lane (one engine), holding the lane until the thread returns.

        Cancelling the caller cannot interrupt a native inference, so the lane is released only
        when the thread really finishes; a lane occupies at most one thread of the pool.
        """
        lock = self._lanes.setdefault(lane, asyncio.Lock())
        await lock.acquire()
        work = asyncio.ensure_future(self.run(fn, *args))
        work.add_done_callback(lambda _: lock.release())
        return await asyncio.shield(work)

    def close(self) -> None:
        """Release the threads without waiting for the work still queued or running."""
        self._pool.shutdown(wait=False, cancel_futures=True)
