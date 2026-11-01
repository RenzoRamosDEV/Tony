import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from tony.apps.desktop.page_protocol import Accepted, EventReplay, PageCommandGate
from tony.apps.desktop.presenters.audit import audit_today
from tony.core.events.core_events import Event, Publisher

Submit = Callable[[dict], None]


class PageBridge(QObject):
    """The object the page sees as `tony` over QWebChannel: core events go out as JSON once the
    page called `ready()`, page commands come in through `send` and are gated first. Its
    signal and slot names are the page-facing JavaScript API, hence camelCase."""

    event = Signal(str)
    focusConfirmation = Signal()

    def __init__(
        self, submit: Submit, report: Publisher, root: Path, *, now: Callable[[], datetime]
    ) -> None:
        super().__init__()
        self._submit = submit
        self._report = report
        self._root = root
        self._now = now
        self._gate = PageCommandGate()
        self._replay = EventReplay()
        self._page_ready = False

    def publish(self, event: Event) -> None:
        self._replay.observe(event)
        if self._page_ready:
            self._emit(event)

    @Slot()
    def ready(self) -> None:
        self._page_ready = True
        for event in self._replay.snapshot():
            self._emit(event)

    @Slot(str)
    def send(self, text: str) -> None:
        outcome = self._gate.accept(text)
        if isinstance(outcome, Accepted):
            self._submit(outcome.command)
            return
        self._emit(outcome.event)
        self._report(outcome.event)

    @Slot(result=str)
    def auditToday(self) -> str:
        return json.dumps(audit_today(self._root, self._now()), ensure_ascii=False)

    def _emit(self, event: Event) -> None:
        self.event.emit(json.dumps(event, ensure_ascii=False))
