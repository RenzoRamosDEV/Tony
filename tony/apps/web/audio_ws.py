"""Audio input of a conversation: frames -> VAD -> STT -> transcript callback, bounded."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum

from tony.core.runner import EventSink
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.ports import (
    FLOAT32_BYTES,
    INPUT_SAMPLE_RATE,
    SPEECH_THRESHOLD,
    Stt,
    Transcript,
    Utterance,
    Vad,
)
from tony.core.voice.utterances import END_SILENCE_MS, UtteranceAssembler, VadSegmenter

STT_FINAL_EVENT = "stt.final"
STT_FAILED = "stt_failed"
AUDIO_BACKPRESSURE = "audio_backpressure"
UTTERANCE_DROPPED = "hay demasiadas intervenciones pendientes de transcribir; se descartó la última"
VAD_LANE = "vad"
STT_LANE = "stt"
MAX_PENDING_SAMPLES = 60 * INPUT_SAMPLE_RATE
MAX_PENDING_UTTERANCES = 2
BARGE_IN_THRESHOLD = 0.8
BARGE_IN_MIN_SPEECH_MS = 280
TranscriptCallback = Callable[[Transcript, bool], Awaitable[None]]
ErrorCallback = Callable[[str, str], Awaitable[None]]
BargeInCallback = Callable[[int], Awaitable[None]]
SttLoader = Callable[[], Stt]


def _never_speaking() -> bool:
    return False


async def _ignore_barge_in(speech_ms: int) -> None:
    return None


class _Command(Enum):
    FLUSH = "flush"
    RESET = "reset"


class AudioSession:
    """Audio input of one conversation: frames -> VAD (serial, off the loop) -> STT -> callback.

    Audio lives in memory only; the log gets `stt.final {chars, duration_ms}` and nothing else.
    One session is reused by every capture of its conversation. Its backlog is bounded: frames
    beyond `max_pending_samples` (queued for VAD plus utterances awaiting STT) are refused, and
    a closed utterance beyond `max_pending_utterances` is dropped (newest first) with an
    `audio_backpressure` error. Utterances are transcribed in speaking order.

    While `speaking()` (Tony's voice is playing) windows are classified with the stricter
    `barge_in_threshold`; once the open utterance gathers `barge_in_min_speech_ms` of speech,
    `on_barge_in` fires once and the utterance goes on, its transcript flagged as
    interrupting. With `barge_in` off, frames heard while Tony speaks are dropped unheard.
    """

    def __init__(
        self,
        vad: Vad,
        stt_loader: SttLoader,
        executor: VoiceExecutor,
        language: str,
        on_final: TranscriptCallback,
        on_error: ErrorCallback,
        events: EventSink,
        max_pending_samples: int = MAX_PENDING_SAMPLES,
        max_pending_utterances: int = MAX_PENDING_UTTERANCES,
        *,
        end_silence_ms: int = END_SILENCE_MS,
        barge_in: bool = True,
        barge_in_threshold: float = BARGE_IN_THRESHOLD,
        barge_in_min_speech_ms: int = BARGE_IN_MIN_SPEECH_MS,
        speaking: Callable[[], bool] = _never_speaking,
        on_barge_in: BargeInCallback = _ignore_barge_in,
    ) -> None:
        self._segmenter = VadSegmenter(vad, UtteranceAssembler(end_silence_ms=end_silence_ms))
        self._barge_in = barge_in
        self._barge_in_threshold = barge_in_threshold
        self._barge_in_min_speech_ms = barge_in_min_speech_ms
        self._speaking = speaking
        self._on_barge_in = on_barge_in
        self._interrupting = False
        self._stt_loader = stt_loader
        self._executor = executor
        self._language = language
        self._on_final = on_final
        self._on_error = on_error
        self._events = events
        self._max_pending_samples = max_pending_samples
        self._max_pending_utterances = max_pending_utterances
        self._pending_samples = 0
        self._stt_backlog = 0
        self._commands: asyncio.Queue[bytes | _Command] = asyncio.Queue()
        self._utterances: asyncio.Queue[tuple[Utterance, bool]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self.capturing = False

    def open(self) -> None:
        """Start a capture; the shared VAD forgets any state left by a previous one."""
        self.capturing = True
        self._send(_Command.RESET)

    def feed(self, frame: bytes) -> bool:
        """Queue a frame for the VAD; False when the backlog budget refuses it."""
        samples = len(frame) // FLOAT32_BYTES
        if self._pending_samples + samples > self._max_pending_samples:
            return False
        self._pending_samples += samples
        self._send(frame)
        return True

    @property
    def busy(self) -> bool:
        """Frames or utterances are still waiting to be segmented or transcribed."""
        return self._pending_samples > 0 or not self._commands.empty()

    def end(self) -> None:
        """Close the capture: what is still pending gets transcribed."""
        self.capturing = False
        self._send(_Command.FLUSH)

    def discard(self) -> None:
        """Drop everything untranscribed, as when the socket goes away."""
        self.capturing = False
        for task in self._tasks:
            task.cancel()

    async def aclose(self) -> None:
        self.discard()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _send(self, command: bytes | _Command) -> None:
        self._commands.put_nowait(command)
        if not self._tasks:
            self._tasks = [
                asyncio.create_task(self._segment_all()),
                asyncio.create_task(self._transcribe_all()),
            ]

    async def _segment_all(self) -> None:
        while True:
            command = await self._commands.get()
            try:
                found = await self._segment(command)
            except Exception as exc:  # noqa: BLE001 - the user learns why, the socket lives on
                await self._on_error(STT_FAILED, f"{exc.__class__.__name__}: {exc}")
                continue
            finally:
                if isinstance(command, bytes):
                    self._pending_samples -= len(command) // FLOAT32_BYTES
            for utterance in found:
                await self._admit(utterance, self._interrupting)
                self._interrupting = False
            if isinstance(command, bytes):
                await self._check_barge_in()

    async def _segment(self, command: bytes | _Command) -> list[Utterance]:
        if command is _Command.RESET:
            self._interrupting = False
            await self._executor.run_serial(VAD_LANE, self._segmenter.reset)
            return []
        if command is _Command.FLUSH:
            return await self._executor.run_serial(VAD_LANE, self._segmenter.flush)
        threshold = SPEECH_THRESHOLD
        if self._speaking():
            if not self._barge_in:
                return []
            threshold = self._barge_in_threshold
        return await self._executor.run_serial(VAD_LANE, self._segmenter.feed, command, threshold)

    async def _check_barge_in(self) -> None:
        speech_ms = self._segmenter.speech_ms
        if speech_ms == 0:
            self._interrupting = False
        elif (
            not self._interrupting
            and speech_ms >= self._barge_in_min_speech_ms
            and self._speaking()
        ):
            self._interrupting = True
            await self._on_barge_in(speech_ms)

    async def _admit(self, utterance: Utterance, interrupting: bool) -> None:
        over_budget = self._pending_samples + utterance.sample_count > self._max_pending_samples
        if self._stt_backlog >= self._max_pending_utterances or over_budget:
            await self._on_error(AUDIO_BACKPRESSURE, UTTERANCE_DROPPED)
            return
        self._stt_backlog += 1
        self._pending_samples += utterance.sample_count
        self._utterances.put_nowait((utterance, interrupting))

    async def _transcribe_all(self) -> None:
        while True:
            utterance, interrupting = await self._utterances.get()
            try:
                transcript = await self._executor.run_serial(STT_LANE, self._transcribe, utterance)
            except Exception as exc:  # noqa: BLE001 - the user learns why, the socket lives on
                await self._on_error(STT_FAILED, f"{exc.__class__.__name__}: {exc}")
                continue
            finally:
                self._stt_backlog -= 1
                self._pending_samples -= utterance.sample_count
            self._events.emit(
                STT_FINAL_EVENT,
                {"chars": len(transcript.text), "duration_ms": transcript.duration_ms},
            )
            if transcript.text.strip():
                await self._on_final(transcript, interrupting)

    def _transcribe(self, utterance: Utterance) -> Transcript:
        return self._stt_loader().transcribe(utterance, self._language)
