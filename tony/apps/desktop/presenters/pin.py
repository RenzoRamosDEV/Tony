import math
import time
from collections.abc import Callable
from typing import Literal

from tony.apps.desktop.presenters.chat import Submit
from tony.apps.desktop.presenters.observable import Observable
from tony.core.events.core_events import Event

PinMode = Literal["hidden", "prompt", "explain"]

ASKING = {"start", "idle", "wrong_pin", "backoff"}
MESSAGES = {
    "start": "Introduzca el PIN de Edith para permitir tareas delegadas.",
    "idle": "La sesión de Edith se ha bloqueado por inactividad. Introduzca el PIN.",
    "wrong_pin": "PIN incorrecto.",
    "backoff": "Demasiados intentos: espere antes de volver a probar.",
    "no_lock_file": (
        "No hay PIN de Edith: Tony funciona en modo solo conversación. "
        "Ejecute `tony pin set` en una terminal para permitir tareas delegadas."
    ),
}


class PinPresenter(Observable):
    """PIN dialog state driven by `auth` events, with a back-off countdown."""

    def __init__(self, submit: Submit, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self._submit = submit
        self._monotonic = monotonic
        self._retry_at = 0.0
        self.mode: PinMode = "hidden"
        self.message = ""
        self.can_unlock = False

    @property
    def remaining_s(self) -> int:
        return max(0, math.ceil(self._retry_at - self._monotonic()))

    @property
    def input_enabled(self) -> bool:
        return self.mode == "prompt" and self.remaining_s == 0

    def apply(self, event: Event) -> None:
        if event["type"] != "auth":
            return
        reason = event["reason"]
        self.can_unlock = event["state"] == "locked"
        self._retry_at = self._monotonic() + event["retry_in_s"]
        self.message = MESSAGES.get(reason, "")
        if reason in ASKING:
            self.mode = "prompt"
        elif reason == "no_lock_file":
            self.mode = "explain"
        else:
            self.mode = "hidden"
        self._changed()

    def tick(self) -> None:
        self._changed()

    def submit(self, pin: str) -> None:
        if pin and self.input_enabled:
            self._submit({"type": "unlock", "pin": pin})

    def cancel(self) -> None:
        self._submit({"type": "unlock", "pin": None})
        self.mode = "hidden"
        self._changed()

    def request_unlock(self) -> None:
        if not self.can_unlock:
            return
        self.mode = "prompt"
        self.message = MESSAGES["start"]
        self._changed()
