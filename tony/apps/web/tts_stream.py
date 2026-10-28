"""Spoken replies on the stream: SpeechPipeline events -> tts.start / chunk.meta + binary / end."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from tony.apps.web.ack_cache import AckCache
from tony.apps.web.playback_window import PlaybackWindow
from tony.apps.web.protocol import (
    ERROR,
    TTS_CANCELLED,
    TTS_CHUNK_META,
    TTS_END,
    TTS_START,
    ConversationStream,
)
from tony.core.channels.ports import AssistantReply
from tony.core.runner import EventSink
from tony.core.voice.cleanup import speech_text_for, spoken_mask
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.pipeline import SpeechPipeline
from tony.core.voice.ports import AudioChunk, Tts
from tony.core.voice.segmenter import SentenceSegmenter

TTS_FAILED = "tts_failed"
SPOKEN_MODES = frozenset({"voice", "both"})
SPOKEN_TEXTS_KEPT = 8
TtsLoader = Callable[[], Tts]


class ReplySink:
    """SpeechSink of one reply: every event becomes an envelope with that reply's message_id."""

    def __init__(
        self, stream: ConversationStream, message_id: str, playback: PlaybackWindow | None = None
    ) -> None:
        self._stream = stream
        self._message_id = message_id
        self._playback = playback or PlaybackWindow(lambda: 0.0)

    async def start(self) -> None:
        self._playback.started(self._message_id)
        await self._publish(TTS_START)

    async def chunk(self, seq: int, sentence_index: int, audio: AudioChunk) -> None:
        self._playback.chunk(self._message_id, audio.duration_ms)
        await self._stream.publish(
            TTS_CHUNK_META,
            {"seq": seq, "sentence_index": sentence_index},
            message_id=self._message_id,
        )
        await self._stream.publish_binary(audio.pcm16, self._message_id)

    async def end(self) -> None:
        self._playback.ended(self._message_id)
        await self._publish(TTS_END)

    async def cancelled(self) -> None:
        self._playback.cancelled(self._message_id)
        self._stream.purge_audio(self._message_id)
        await self._publish(TTS_CANCELLED)

    async def failed(self, error: str) -> None:
        await self._stream.publish(
            ERROR, {"code": TTS_FAILED, "detail": error}, message_id=self._message_id
        )

    async def _publish(self, type_: str) -> None:
        await self._stream.publish(
            type_, {"message_id": self._message_id}, message_id=self._message_id
        )


class SpeechStreamer:
    """Starts, feeds and cancels one SpeechPipeline per spoken reply of a conversation."""

    def __init__(
        self,
        stream: ConversationStream,
        tts_loader: TtsLoader,
        executor: VoiceExecutor,
        voice: str,
        events: EventSink,
        playback: PlaybackWindow | None = None,
        acks: AckCache | None = None,
    ) -> None:
        self._stream = stream
        self._acks = acks
        self._tts_loader = tts_loader
        self._executor = executor
        self._voice = voice
        self._events = events
        self._playback = playback or PlaybackWindow(lambda: 0.0)
        self._pipelines: dict[str, SpeechPipeline] = {}
        self._finishers: set[asyncio.Task[None]] = set()
        self._spoken: dict[str, str] = {}
        self._streamed: set[str] = set()

    def on_delta(self, message_id: str, text: str) -> None:
        self._streamed.add(message_id)
        self._remember_spoken(message_id, text)
        self._pipeline_for(message_id).feed(text)

    def acknowledge(self, message_id: str, mode: str) -> None:
        """A spoken reply delegated a task: play a cached acknowledgement as its first piece,
        unless the cache is not ready yet or the reply already has audio of its own."""
        if self._acks is None or mode not in SPOKEN_MODES or message_id in self._pipelines:
            return
        self._acks.warm()
        acknowledgement = self._acks.next()
        if acknowledgement is not None:
            phrase, audio = acknowledgement
            self._remember_spoken(message_id, phrase + " ")
            self._pipeline_for(message_id).feed_audio(audio)

    def start(self, reply: AssistantReply) -> None:
        """Speak a reply in voice/both: at once from its full text, or finishing streamed deltas.

        A reply cut short by the user's voice is never spoken.
        """
        if reply.mode not in SPOKEN_MODES or reply.message_id is None:
            return
        streamed = reply.message_id in self._streamed
        if reply.interrupted and not streamed:
            return
        pipeline = self._pipeline_for(reply.message_id)
        if not streamed:
            redact = self._stream.redact_text
            speech = None if reply.speech_text is None else redact(reply.speech_text)
            text = speech_text_for(redact(reply.display_text), speech).text
            self._remember_spoken(reply.message_id, text)
            pipeline.feed(text)
        finisher = asyncio.create_task(self._finish(reply.message_id, pipeline))
        self._finishers.add(finisher)
        finisher.add_done_callback(self._finishers.discard)

    @property
    def speaking(self) -> list[str]:
        return [m for m, p in self._pipelines.items() if not p.finished]

    async def cancel(self, message_id: str) -> bool:
        pipeline = self._pipelines.get(message_id)
        if pipeline is None or pipeline.finished:
            return False
        await pipeline.cancel()
        return True

    async def cancel_all(self) -> None:
        for message_id in self.speaking:
            await self.cancel(message_id)

    async def stop_playing(self, message_ids: list[str]) -> None:
        """Stop these replies everywhere: still synthesizing or already sent and playing."""
        for message_id in message_ids:
            if not await self.cancel(message_id):
                await ReplySink(self._stream, message_id, self._playback).cancelled()

    def spoken_text(self, message_ids: list[str]) -> str:
        return " ".join(self._spoken.get(message_id, "") for message_id in message_ids)

    async def aclose(self) -> None:
        await self.cancel_all()
        finishers = list(self._finishers)
        for finisher in finishers:
            finisher.cancel()
        await asyncio.gather(*finishers, return_exceptions=True)

    def _pipeline_for(self, message_id: str) -> SpeechPipeline:
        if message_id not in self._pipelines:
            self._pipelines[message_id] = SpeechPipeline(
                self._tts_loader,
                self._executor,
                self._voice,
                ReplySink(self._stream, message_id, self._playback),
                self._events,
                segmenter=SentenceSegmenter(first_clause=True),
                sanitize=self._speakable,
            )
        return self._pipelines[message_id]

    def _remember_spoken(self, message_id: str, text: str) -> None:
        self._spoken[message_id] = self._spoken.pop(message_id, "") + text
        while len(self._spoken) > SPOKEN_TEXTS_KEPT:
            del self._spoken[next(iter(self._spoken))]

    def _speakable(self, sentence: str) -> str:
        """Secrets are masked per whole sentence, so one split across deltas is caught too."""
        return spoken_mask(self._stream.redact_text(sentence))

    async def _finish(self, message_id: str, pipeline: SpeechPipeline) -> None:
        try:
            await pipeline.finish()
        finally:
            self._pipelines.pop(message_id, None)
            self._streamed.discard(message_id)
