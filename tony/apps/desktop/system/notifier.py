import asyncio
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

APP_NAME = "Tony"
SEND_TIMEOUT_S = 2
STOP_TIMEOUT_S = 2


class DesktopNotifications(QObject):
    """desktop-notifier on its own `tony-notify` thread and asyncio loop; a click is brought
    back to the Qt main thread by a signal. `notify` raises when the notification fails."""

    _clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._notifier: Any = None
        self._on_click: Callable[[], None] = lambda: None
        self._clicked.connect(self._run_click)

    def notify(self, title: str, body: str, on_click: Callable[[], None]) -> None:
        loop = self._start()
        self._on_click = on_click
        sending = asyncio.run_coroutine_threadsafe(self._send(title, body), loop)
        sending.result(SEND_TIMEOUT_S)

    def close(self) -> None:
        if self._loop is not None and self._thread is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(STOP_TIMEOUT_S)

    def _start(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            from desktop_notifier import DesktopNotifier

            self._notifier = DesktopNotifier(app_name=APP_NAME)
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, name="tony-notify", daemon=True
            )
            self._thread.start()
        return self._loop

    async def _send(self, title: str, body: str) -> None:
        await self._notifier.send(title=title, message=body, on_clicked=self._clicked.emit)

    @Slot()
    def _run_click(self) -> None:
        self._on_click()
