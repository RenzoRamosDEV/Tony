"""One open audio utterance of a conversation: frames -> VAD -> STT -> transcript callback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from tony.core.runner import EventSink
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.ports import Stt, Transcript, Utterance, Vad
from tony.core.voice.utterances import VadSegmenter

STT_FINAL_EVENT = "stt.final"
STT_FAILED = "stt_failed"
TranscriptCallback = Callable[[Transcript], Awaitable[None]]
ErrorCallback = Callable[[str, str], Awaitable[None]]
SttLoader = Callable[[], Stt]


class AudioSession:
    """Audio lives in memory only; the log gets `stt.final {chars, duration_ms}` and nothing else.

    Utterances are transcribed one after another so `stt.final` keeps the speaking order.
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
    ) -> None:
        self._segmenter = VadSegmenter(vad)
        self._stt_loader = stt_loader
        self._executor = executor
        self._language = language
        self._on_final = on_final
        self._on_error = on_error
        self._events = events
        self._pending: asyncio.Queue[Utterance | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def feed(self, frame: bytes) -> None:
        for utterance in self._segmenter.feed(frame):
            self._enqueue(utterance)

    def end(self) -> None:
        """Close the utterance: what is still pending gets transcribed, nothing more is taken."""
        for utterance in self._segmenter.flush():
            self._enqueue(utterance)
        if self._worker is not None:
            self._pending.put_nowait(None)

    def discard(self) -> None:
        """Drop everything untranscribed, as when the socket goes away."""
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
        while not self._pending.empty():
            self._pending.get_nowait()

    @property
    def transcribing(self) -> bool:
        return self._worker is not None and not self._worker.done()

    def _enqueue(self, utterance: Utterance) -> None:
        self._pending.put_nowait(utterance)
        if self._worker is None:
            self._worker = asyncio.create_task(self._transcribe_all())

    async def _transcribe_all(self) -> None:
        while (utterance := await self._pending.get()) is not None:
            try:
                stt = await self._executor.run(self._stt_loader)
                transcript = await self._executor.run(stt.transcribe, utterance, self._language)
            except Exception as exc:  # noqa: BLE001 - the user learns why, the socket lives on
                await self._on_error(STT_FAILED, f"{exc.__class__.__name__}: {exc}")
                continue
            self._events.emit(
                STT_FINAL_EVENT,
                {"chars": len(transcript.text), "duration_ms": transcript.duration_ms},
            )
            if transcript.text.strip():
                await self._on_final(transcript)
