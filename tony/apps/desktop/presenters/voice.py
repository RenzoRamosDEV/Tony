from tony.apps.desktop.presenters.chat import Submit
from tony.apps.desktop.presenters.observable import Observable
from tony.core.events.core_events import Event, VoiceState

MICROPHONE_LABEL = "Micrófono"
LISTENING_LABEL = "Escuchando…"
_TOOLTIPS: dict[VoiceState, str] = {
    "loading": "Cargando los modelos de voz…",
    "ready": "Pulse para decir una frase",
    "listening": "Escuchando: pulse para parar",
}


class VoicePresenter(Observable):
    """Microphone button state, driven by `voice_state` events."""

    def __init__(self, submit: Submit) -> None:
        super().__init__()
        self._submit = submit
        self.state: VoiceState = "loading"
        self._reason: str | None = None

    @property
    def enabled(self) -> bool:
        return self.state in ("ready", "listening")

    @property
    def label(self) -> str:
        return LISTENING_LABEL if self.state == "listening" else MICROPHONE_LABEL

    @property
    def tooltip(self) -> str:
        if self.state == "unavailable":
            return f"Voz no disponible: {self._reason}"
        return _TOOLTIPS[self.state]

    def toggle(self) -> None:
        if self.state == "ready":
            self._submit({"type": "listen"})
        elif self.state == "listening":
            self._submit({"type": "stop_listening"})

    def apply(self, event: Event) -> None:
        if event["type"] != "voice_state":
            return
        self.state, self._reason = event["state"], event["reason"]
        self._changed()
