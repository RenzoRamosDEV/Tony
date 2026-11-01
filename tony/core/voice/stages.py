import queue
import threading
from collections.abc import Callable
from typing import Any

STOP_TIMEOUT_S = 2
THREAD_PREFIX = "tony-"

Report = Callable[[str, str], None]
_STOP = object()


class StageThread:
    """Runs `handle` on each queued item in its own `tony-<stage>` thread. A failing item is
    reported as source `voice.<stage>` and dropped; the loop goes on with the next one."""

    def __init__(self, stage: str, handle: Callable[[Any], None], report: Report) -> None:
        self._stage = stage
        self._handle = handle
        self._report = report
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name=THREAD_PREFIX + stage, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def put(self, item: Any) -> None:
        self._queue.put(item)

    def clear(self) -> int:
        """Drop the queued items; returns how many were dropped."""
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return dropped
            dropped += 1

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self) -> None:
        if not self._thread.is_alive():
            return
        self._queue.put(_STOP)
        self._thread.join(STOP_TIMEOUT_S)

    def _run(self) -> None:
        while (item := self._queue.get()) is not _STOP:
            try:
                self._handle(item)
            except Exception as error:
                self._report(f"voice.{self._stage}", str(error) or type(error).__name__)
