import asyncio
from pathlib import Path


class FakeChanges:
    """Injected change-stream factory: tests push batches of paths; `handled` counts batches
    the consumer finished (it asked for the next one)."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[set[Path]] = asyncio.Queue()
        self.handled = 0
        self.started: list[tuple[Path, str]] = []
        self.stop: asyncio.Event | None = None
        self.closed = False
        self._from_threads: list[set[Path]] = []

    def __call__(self, root: Path, guard: str, stop: asyncio.Event):
        self.started.append((root, guard))
        self.stop = stop
        return self._stream()

    async def _stream(self):
        try:
            while True:
                batch = await self._next()
                yield batch
                self.handled += 1
        finally:
            self.closed = True

    async def _next(self) -> set[Path]:
        while self.queue.empty():
            if self._from_threads:
                return self._from_threads.pop(0)
            await asyncio.sleep(0.01)
        return self.queue.get_nowait()

    def push_from_thread(self, *paths: Path) -> None:
        """Push from a non-event-loop thread (e.g. a paced console reader)."""
        self._from_threads.append(set(paths))

    async def push(self, *paths: Path, timeout: float = 5.0) -> None:
        target = self.handled + 1
        self.queue.put_nowait(set(paths))
        async with asyncio.timeout(timeout):
            while self.handled < target:
                await asyncio.sleep(0.01)
