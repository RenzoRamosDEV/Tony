"""Sentence-level speech pipeline: text fragments -> sentences -> Tts (one at a time) -> sink."""

from __future__ import annotations

import asyncio
import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass

from tony.core.runner import EventSink
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.ports import AudioChunk, SpeechSink, Tts
from tony.core.voice.segmenter import SentenceSegmenter

TTS_EVENT = "tts"
TtsLoader = Callable[[], Tts]


@dataclass
class SpeechStats:
    sentences: int = 0
    duration_ms: int = 0

    def add(self, chunks: list[AudioChunk]) -> None:
        self.sentences += 1
        self.duration_ms += sum(chunk.duration_ms for chunk in chunks)

    def report(self, events: EventSink, cancelled: bool) -> None:
        events.emit(
            TTS_EVENT,
            {"sentences": self.sentences, "duration_ms": self.duration_ms, "cancelled": cancelled},
        )


class SpeechPipeline:
    """`feed` text as it arrives, `finish` when it is complete, `cancel` to stop everything.

    A single consumer synthesizes one sentence at a time on the voice executor, so STT keeps
    the other thread; a Tts failure degrades the reply to text (`failed` + `cancelled`).
    """

    def __init__(
        self,
        tts_loader: TtsLoader,
        executor: VoiceExecutor,
        voice: str,
        sink: SpeechSink,
        events: EventSink,
        segmenter: SentenceSegmenter | None = None,
    ) -> None:
        self._tts_loader = tts_loader
        self._executor = executor
        self._voice = voice
        self._sink = sink
        self._events = events
        self._segmenter = segmenter or SentenceSegmenter()
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._consumer: asyncio.Task[None] | None = None
        self._stop = threading.Event()
        self._stats = SpeechStats()
        self._finished = False
        self._seq = 0
        self._sentence_index = 0

    @property
    def finished(self) -> bool:
        return self._finished

    def feed(self, text: str) -> None:
        for sentence in self._segmenter.feed(text):
            self._enqueue(sentence)

    async def finish(self) -> None:
        rest = self._segmenter.flush()
        if rest is not None:
            self._enqueue(rest)
        if self._consumer is None:
            self._settle(cancelled=False)
            return
        self._queue.put_nowait(None)
        await asyncio.gather(self._consumer, return_exceptions=True)

    async def cancel(self) -> None:
        if self._finished:
            return
        self._stop.set()
        consumer = self._consumer
        if consumer is not None and not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        self._settle(cancelled=True)
        await self._sink.cancelled()

    def _enqueue(self, sentence: str) -> None:
        if self._finished or self._stop.is_set():
            return
        self._queue.put_nowait(sentence)
        if self._consumer is None:
            self._consumer = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        try:
            tts = await self._executor.run(self._tts_loader)
        except Exception as exc:  # noqa: BLE001 - a broken engine degrades the reply to text
            await self._sink.failed(f"{exc.__class__.__name__}: {exc}")
            self._settle(cancelled=True)
            return
        await self._sink.start()
        while (sentence := await self._queue.get()) is not None:
            try:
                chunks = await self._executor.run(self._synthesize, tts, sentence)
            except Exception as exc:  # noqa: BLE001 - same degradation, after some audio
                await self._sink.failed(f"{exc.__class__.__name__}: {exc}")
                self._settle(cancelled=True)
                await self._sink.cancelled()
                return
            for chunk in chunks:
                await self._sink.chunk(self._seq, self._sentence_index, chunk)
                self._seq += 1
            self._sentence_index += 1
            self._stats.add(chunks)
        self._settle(cancelled=False)
        await self._sink.end()

    def _synthesize(self, tts: Tts, sentence: str) -> list[AudioChunk]:
        stream = tts.synthesize(sentence, self._voice)
        return list(itertools.takewhile(lambda _: not self._stop.is_set(), stream))

    def _settle(self, cancelled: bool) -> None:
        self._finished = True
        self._stop.set()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._stats.report(self._events, cancelled)
