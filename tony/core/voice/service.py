import asyncio
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tony.core.config.settings import VoiceSettings
from tony.core.events import core_events
from tony.core.events.core_events import Event, Publisher, VoiceState
from tony.core.voice.answer import is_voice_yes, spoken_question
from tony.core.voice.listener import Listener
from tony.core.voice.ports import Engines, Unavailable
from tony.core.voice.speaker import Speaker
from tony.core.voice.spoken import TurnSpeech
from tony.core.voice.stages import STOP_TIMEOUT_S, THREAD_PREFIX

IDLE_TIMEOUT_S = 10.0
FLUSH_AFTER_S = 0.3
_SUPPORTED_STT = re.compile(r"^faster-whisper/[\w.-]+$")
SUPPORTED_VAD = "silero"

EngineLoader = Callable[[VoiceSettings, tuple[str, ...]], Engines | Unavailable]
Post = Callable[[Callable[[], Any]], Any]
Submit = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class VoiceCast:
    front: str
    front_voice: str
    worker_voice: str
    guard_voice: str

    @property
    def voices(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.front_voice, self.worker_voice, self.guard_voice)))


def unsupported_setting(settings: VoiceSettings) -> str | None:
    if not _SUPPORTED_STT.match(settings.stt):
        return f"voice.stt '{settings.stt}' is not supported: use faster-whisper/<model>"
    if settings.vad != SUPPORTED_VAD:
        return f"voice.vad '{settings.vad}' is not supported: use {SUPPORTED_VAD}"
    return None


class VoiceService:
    """Voice around the core: observes published events to speak speaking turns and Edith's
    questions, and turns transcripts into `send_message` or `confirm` commands.

    Every method except the engine callbacks runs on the core loop thread; the voice threads
    hand their results back through `post`, so events are only published from that thread.
    """

    def __init__(
        self,
        loader: EngineLoader,
        *,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
        flush_after_s: float = FLUSH_AFTER_S,
    ) -> None:
        self._loader = loader
        self._idle_timeout_s = idle_timeout_s
        self._flush_after_s = flush_after_s
        self._state: VoiceState = "loading"
        self._reason: str | None = None
        self._speaker: Speaker | None = None
        self._listener: Listener | None = None
        self._loading: threading.Thread | None = None
        self._listen_when_ready = False
        self._turn: TurnSpeech | None = None
        self._flush: asyncio.TimerHandle | None = None
        self._armed: str | None = None
        self._closed = False

    @property
    def ready(self) -> bool:
        return self._speaker is not None and self._state in ("ready", "listening")

    def start(
        self,
        settings: VoiceSettings,
        cast: VoiceCast,
        *,
        publish: Publisher,
        submit: Submit,
        post: Post,
    ) -> None:
        self._cast = cast
        self._publish = publish
        self._submit = submit
        self._post = post
        self._set_state("loading")
        problem = unsupported_setting(settings)
        if problem is not None:
            self._set_state("unavailable", problem)
            return
        self._loading = threading.Thread(
            target=self._load, args=(settings,), name=THREAD_PREFIX + "voice-load", daemon=True
        )
        self._loading.start()

    def listen(self) -> None:
        if self._state == "loading":
            self._listen_when_ready = True
        elif self._state == "unavailable":
            self._publish(core_events.error("listen", self._reason or "voice is unavailable"))
        elif self._state == "ready":
            self._open_session()

    def stop_listening(self) -> None:
        self._listen_when_ready = False
        if self._listener is not None:
            self._listener.stop()

    def stop_speaking(self) -> None:
        self._turn = None
        self._cancel_flush()
        if self._speaker is not None:
            self._speaker.stop_speaking()

    def wait_silent(self, timeout: float) -> bool:
        return self._speaker is None or self._speaker.wait_drained(timeout)

    def observe(self, event: Event) -> None:
        kind = event["type"]
        if kind == "token":
            self._on_token(event)
            return
        if self._turn is not None:
            self._turn.flush()
        if kind == "turn_started":
            self._on_turn_started(event)
        elif kind == "progress" and self._turn is not None:
            self._say(event["text"], self._cast.front_voice)
        elif kind == "result":
            self._on_result(event)
        elif kind == "error" and event["source"] == "front":
            self.stop_speaking()
        elif kind == "needs_confirmation":
            self._on_needs_confirmation(event)
        elif kind == "tool_call":
            self._disarm(event["task_id"])

    def close(self) -> None:
        self._closed = True
        self._cancel_flush()
        if self._listener is not None:
            self._listener.close()
        if self._speaker is not None:
            self._speaker.close()
        if self._loading is not None:
            self._loading.join(STOP_TIMEOUT_S)

    def _load(self, settings: VoiceSettings) -> None:
        try:
            outcome = self._loader(settings, self._cast.voices)
        except Exception as error:
            outcome = Unavailable(str(error) or type(error).__name__)
        self._post(lambda: self._loaded(outcome))

    def _loaded(self, outcome: Engines | Unavailable) -> None:
        if self._closed:
            return
        if isinstance(outcome, Unavailable):
            self._set_state("unavailable", outcome.reason)
            return
        self._speaker = Speaker(outcome.tts, outcome.audio_output, self._report)
        self._listener = Listener(outcome.audio_input, outcome.vad, outcome.stt, self._report)
        self._speaker.start()
        self._listener.start()
        self._set_state("ready")
        if self._listen_when_ready:
            self._listen_when_ready = False
            self._open_session()

    def _open_session(self, *, for_confirmation: bool = False) -> None:
        assert self._listener is not None
        self.stop_speaking()
        self._set_state("listening")
        self._listener.listen(
            lambda text: self._post(lambda: self._on_transcript(text)),
            lambda: self._post(self._on_session_end),
            idle_timeout_s=None if for_confirmation else self._idle_timeout_s,
        )

    def _on_transcript(self, text: str) -> None:
        if self._armed is not None:
            decision = "allow" if is_voice_yes(text) else "deny"
            self._submit({"type": "confirm", "task_id": self._armed, "decision": decision})
            self._armed = None
            return
        self._publish(core_events.transcript(text))
        self._submit({"type": "send_message", "text": text, "origin": "voice"})

    def _on_session_end(self) -> None:
        if self._state == "listening":
            self._set_state("ready")

    def _on_turn_started(self, event: Event) -> None:
        speaks = event["speaks"] and self._speaker is not None
        self._turn = TurnSpeech(self._cast.front_voice, self._say) if speaks else None

    def _on_token(self, event: Event) -> None:
        if self._turn is None or event["agent"] != self._cast.front:
            return
        self._turn.feed(event["text"])
        self._cancel_flush()
        self._flush = asyncio.get_running_loop().call_later(self._flush_after_s, self._flush_turn)

    def _flush_turn(self) -> None:
        self._flush = None
        if self._turn is not None:
            self._turn.flush()

    def _cancel_flush(self) -> None:
        if self._flush is not None:
            self._flush.cancel()
            self._flush = None

    def _on_result(self, event: Event) -> None:
        if event["scope"] == "task":
            self._disarm(event["task_id"])
        elif self._turn is not None:
            self._cancel_flush()
            self._turn.finish()
            self._turn = None

    def _on_needs_confirmation(self, event: Event) -> None:
        if self._turn is None or self._speaker is None:
            return
        self._armed = event["task_id"]
        self._say(spoken_question(event["question"]), self._cast.guard_voice)
        task_id = event["task_id"]
        self._speaker.on_drained(lambda: self._post(lambda: self._ask_by_voice(task_id)))

    def _ask_by_voice(self, task_id: str) -> None:
        if self._armed == task_id and self._state == "ready":
            self._open_session(for_confirmation=True)

    def _disarm(self, task_id: str) -> None:
        if self._armed != task_id:
            return
        self._armed = None
        self.stop_listening()

    def _say(self, text: str, voice: str) -> None:
        if self._speaker is not None:
            self._speaker.say(text, voice)

    def _report(self, source: str, message: str) -> None:
        self._post(lambda: self._publish(core_events.error(source, message)))

    def _set_state(self, state: VoiceState, reason: str | None = None) -> None:
        self._state, self._reason = state, reason
        self._publish(core_events.voice_state(state, reason))
