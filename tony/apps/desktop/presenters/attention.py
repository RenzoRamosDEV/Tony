from collections.abc import Callable
from typing import Protocol

from tony.core.events import core_events
from tony.core.events.core_events import Event

NOTIFICATION_TITLE = "Tony — Edith"
NOTIFICATIONS_SOURCE = "notifications"


class Notifier(Protocol):
    def notify(self, title: str, body: str, on_click: Callable[[], None]) -> None: ...


class ConfirmationAttention:
    """Shows one native notification per pending confirmation while the window is out of
    sight; clicking it reveals the confirmation card. A failing notifier is reported once."""

    def __init__(
        self,
        notifier: Notifier,
        *,
        window_hidden: Callable[[], bool],
        reveal: Callable[[bool], None],
        report: Callable[[Event], None],
    ) -> None:
        self._notifier = notifier
        self._window_hidden = window_hidden
        self._reveal = reveal
        self._report = report
        self._notified: set[tuple[str, str]] = set()
        self._broken = False

    def apply(self, event: Event) -> None:
        if event["type"] != "needs_confirmation" or self._broken:
            return
        key = (event["task_id"], event["ts"])
        if key in self._notified or not self._window_hidden():
            return
        self._notified.add(key)
        try:
            self._notifier.notify(NOTIFICATION_TITLE, event["question"], self.clicked)
        except Exception as error:
            self._broken = True
            message = str(error) or type(error).__name__
            self._report(core_events.error(NOTIFICATIONS_SOURCE, message))

    def clicked(self) -> None:
        self._reveal(True)
