import asyncio
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Any, Protocol

from PySide6.QtCore import QObject, Signal

from tony.core.events import core_events
from tony.core.events.core_events import Event, Publisher

STOP_TIMEOUT_S = 5.0


class Runtime(Protocol):
    def submit(self, raw: Any) -> None: ...

    async def serve(self) -> None: ...


class QtEventBridge(QObject):
    """Core events cross into the Qt main thread only through this signal (queued delivery)."""

    event = Signal(object)

    def publish(self, event: Event) -> None:
        self.event.emit(event)


class CoreThread:
    """Runs the core runtime in its own thread and asyncio loop; the UI only submits commands."""

    def __init__(self, runtime_factory: Callable[[Publisher], Runtime], bridge: QtEventBridge):
        self._runtime_factory = runtime_factory
        self._bridge = bridge
        self._thread = threading.Thread(target=self._run, name="tony-core", daemon=True)
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runtime: Runtime | None = None
        self._serving: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(STOP_TIMEOUT_S)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, command: dict[str, Any]) -> None:
        if self._loop is not None and self.is_alive():
            with suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._deliver, command)

    def stop(self) -> None:
        if self._loop is not None and self.is_alive():
            with suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._request_stop)
        self._thread.join(STOP_TIMEOUT_S)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._runtime = self._runtime_factory(self._bridge.publish)
            self._serving = loop.create_task(self._serve(self._runtime))
        except Exception as error:
            self._report("core", error)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _serve(self, runtime: Runtime) -> None:
        try:
            await runtime.serve()
        except Exception as error:
            self._report("core", error)

    def _deliver(self, command: dict[str, Any]) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.submit(command)
        except Exception as error:
            self._report(str(command.get("type")), error)

    def _request_stop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._serving is None or self._serving.done():
            loop.stop()
            return
        self._serving.add_done_callback(lambda _: loop.stop())
        self._deliver({"type": "stop"})

    def _report(self, source: str, error: Exception) -> None:
        self._bridge.publish(core_events.error(source, str(error) or type(error).__name__))
