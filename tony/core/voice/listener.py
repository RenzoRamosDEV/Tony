import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from tony.core.voice.ports import WINDOW_BYTES, AudioInput, Stt, Vad
from tony.core.voice.stages import Report, StageThread
from tony.core.voice.utterances import UtteranceAssembler


@dataclass(eq=False)
class _Session:
    on_transcript: Callable[[str], None]
    on_end: Callable[[], None]
    idle_timeout_s: float | None
    started: float
    capturing: bool = True
    heard: bool = field(default=False)


class Listener:
    """One-utterance listening sessions: microphone frames go to the `tony-vad` thread, which
    closes the microphone when the utterance ends; `tony-stt` transcribes it. Callbacks run on
    those threads: `on_transcript` for a non-empty transcript, then `on_end` exactly once."""

    def __init__(
        self,
        audio: AudioInput,
        vad: Vad,
        stt: Stt,
        report: Report,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._audio = audio
        self._vad = vad
        self._stt = stt
        self._report = report
        self._clock = clock
        self._lock = threading.Lock()
        self._session: _Session | None = None
        self._vad_session: _Session | None = None
        self._assembler = UtteranceAssembler()
        self._pending = b""
        self._detection = StageThread("vad", self._detect, report)
        self._transcription = StageThread("stt", self._transcribe, report)

    @property
    def listening(self) -> bool:
        return self._session is not None

    def start(self) -> None:
        self._detection.start()
        self._transcription.start()

    def listen(
        self,
        on_transcript: Callable[[str], None],
        on_end: Callable[[], None],
        *,
        idle_timeout_s: float | None = None,
    ) -> None:
        self.stop()
        session = _Session(on_transcript, on_end, idle_timeout_s, self._clock())
        with self._lock:
            self._session = session
        try:
            self._audio.open(lambda frame: self._detection.put((session, frame)))
        except Exception as error:
            session.capturing = False
            self._report("voice.capture", str(error) or type(error).__name__)
            self._end(session)

    def stop(self) -> None:
        session = self._session
        if session is not None:
            self._end(session)

    def close(self) -> None:
        self.stop()
        self._detection.stop()
        self._transcription.stop()

    def _detect(self, item: tuple[_Session, bytes]) -> None:
        session, frame = item
        if session is not self._session or not session.capturing:
            return
        if session is not self._vad_session:
            self._vad_session = session
            self._assembler.reset()
            self._vad.reset()
            self._pending = b""
        self._pending += frame
        while len(self._pending) >= WINDOW_BYTES and session.capturing:
            window, self._pending = self._pending[:WINDOW_BYTES], self._pending[WINDOW_BYTES:]
            self._detect_window(session, window)

    def _detect_window(self, session: _Session, window: bytes) -> None:
        speech = self._vad.is_speech(window)
        session.heard = session.heard or speech
        utterance = self._assembler.push(window, speech)
        if utterance is not None:
            self._close_capture(session)
            self._transcription.put((session, utterance))
        elif self._idle_expired(session):
            self._end(session)

    def _idle_expired(self, session: _Session) -> bool:
        if session.heard or session.idle_timeout_s is None:
            return False
        return self._clock() - session.started >= session.idle_timeout_s

    def _transcribe(self, item: tuple[_Session, bytes]) -> None:
        session, pcm = item
        try:
            text = self._stt.transcribe(pcm).strip()
        except Exception:
            self._end(session)
            raise
        if text and session is self._session:
            session.on_transcript(text)
        self._end(session)

    def _close_capture(self, session: _Session) -> None:
        with self._lock:
            was_capturing, session.capturing = session.capturing, False
        if was_capturing:
            self._audio.close()

    def _end(self, session: _Session) -> None:
        with self._lock:
            if self._session is not session:
                return
            self._session = None
        self._close_capture(session)
        session.on_end()
