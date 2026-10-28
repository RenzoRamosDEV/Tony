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

    async def run[T](self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, partial(fn, *args))

    def close(self) -> None:
        """Release the threads without waiting for the work still queued or running."""
        self._pool.shutdown(wait=False, cancel_futures=True)
