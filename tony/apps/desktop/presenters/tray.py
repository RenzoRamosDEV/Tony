from typing import Literal

from tony.apps.desktop.presenters.chat import NEUTRAL
from tony.apps.desktop.presenters.observable import Observable
from tony.core.events.core_events import Event

TrayState = Literal["idle", "working", "awaiting_confirmation"]
TRAY_LOOKS: dict[TrayState, tuple[str, str]] = {
    "idle": ("Tony — en espera", NEUTRAL),
    "working": ("Tony — trabajando", "#2F6FED"),
    "awaiting_confirmation": ("Tony — esperando confirmación", "#E0A100"),
}


class TrayPresenter(Observable):
    """Tray state: idle, working on a turn or task, or awaiting a confirmation."""

    def __init__(self) -> None:
        super().__init__()
        self.state: TrayState = "idle"
        self._awaiting: str | None = None

    @property
    def tooltip(self) -> str:
        return TRAY_LOOKS[self.state][0]

    @property
    def colour(self) -> str:
        return TRAY_LOOKS[self.state][1]

    def apply(self, event: Event) -> None:
        kind = event["type"]
        if kind in ("turn_started", "task_started"):
            self._set("working")
        elif kind == "needs_confirmation":
            self._awaiting = event["task_id"]
            self._set("awaiting_confirmation")
        elif kind == "tool_call" and event["task_id"] == self._awaiting:
            self._answered()
        elif kind == "result" and event["scope"] == "task":
            self._answered()
        elif kind == "result" or (kind == "error" and event["source"] == "front"):
            self._set("idle")

    def _answered(self) -> None:
        self._awaiting = None
        self._set("working")

    def _set(self, state: TrayState) -> None:
        if state != self.state:
            self.state = state
            self._changed()
