import asyncio
import threading


class FakeRuntime:
    """Runtime double: echoes commands as events from the core thread; `boom` raises."""

    def __init__(self, publish, *, crash_on_serve: bool = False) -> None:
        self.publish = publish
        self.crash_on_serve = crash_on_serve
        self.commands: list[dict] = []
        self.submit_threads: list[int] = []
        self.serve_thread: int | None = None
        self.stopped = False
        self._queue: asyncio.Queue = asyncio.Queue()

    def submit(self, raw: dict) -> None:
        self.submit_threads.append(threading.get_ident())
        if raw.get("type") == "boom":
            raise RuntimeError("boom")
        self._queue.put_nowait(raw)

    async def serve(self) -> None:
        self.serve_thread = threading.get_ident()
        if self.crash_on_serve:
            raise RuntimeError("serve crashed")
        while True:
            raw = await self._queue.get()
            if raw.get("type") == "stop":
                self.stopped = True
                return
            self.commands.append(raw)
            self.publish({"type": "echo", "command": raw, "thread": threading.get_ident()})
