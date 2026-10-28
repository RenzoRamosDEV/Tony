"""Pre-synthesized acknowledgements for delegations (specs/voice-output: Acuses pregrabados)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from tests.fakes.sinks import ListEventSink
from tests.fakes.voice import FakeTts
from tony.apps.web.ack_cache import AckCache
from tony.apps.web.protocol import ConversationStream
from tony.apps.web.tts_stream import SpeechStreamer
from tony.core.channels.ports import AssistantReply
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.ports import AudioChunk

PHRASES = ["Un momento, señor.", "Enseguida, señor.", "Ahora mismo lo reviso, señor."]


class TextTts:
    """Audio that spells its text, so a test can tell which phrase it hears."""

    def __init__(self, fail: bool = False) -> None:
        self.texts: list[str] = []
        self.fail = fail

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        self.texts.append(text)
        if self.fail:
            raise RuntimeError("motor roto")
        yield AudioChunk(text.encode("utf-8") + b"\0" * (len(text.encode("utf-8")) % 2))


@pytest.fixture
def executor() -> Iterator[VoiceExecutor]:
    executor = VoiceExecutor()
    yield executor
    executor.close()


async def until(condition, timeout: float = 3.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("la condición no se cumplió")


def spelled(acknowledgement: tuple[str, list[AudioChunk]] | None) -> str:
    assert acknowledgement is not None
    phrase, chunks = acknowledgement
    audio = b"".join(c.pcm16 for c in chunks).rstrip(b"\0").decode("utf-8")
    assert audio == phrase
    return phrase


async def test_nothing_is_ready_before_warming(executor) -> None:
    cache = AckCache(PHRASES, lambda: TextTts(), executor, "v")

    assert not cache.ready
    assert cache.next() is None


async def test_warm_synthesizes_each_phrase_once_and_rotates_in_order(executor) -> None:
    tts = TextTts()
    cache = AckCache(PHRASES, lambda: tts, executor, "v")

    cache.warm()
    cache.warm()
    await until(lambda: cache.ready)
    cache.warm()
    heard = [spelled(cache.next()) for _ in range(4)]

    assert tts.texts == PHRASES
    assert heard == [*PHRASES, PHRASES[0]]


async def test_a_broken_engine_leaves_the_cache_unready_without_raising(executor) -> None:
    cache = AckCache(PHRASES, lambda: TextTts(fail=True), executor, "v")

    cache.warm()
    await asyncio.sleep(0.1)

    assert not cache.ready and cache.next() is None


def streamer_with(cache: AckCache, executor, tts) -> tuple[SpeechStreamer, ConversationStream]:
    stream = ConversationStream("c1")
    streamer = SpeechStreamer(stream, lambda: tts, executor, "v", ListEventSink(), acks=cache)
    return streamer, stream


def published(stream: ConversationStream) -> list[tuple[str, str | None, dict]]:
    return [(e.type, e.message_id, e.payload) for e in stream.replay(0) or []]


async def wait_quiet(streamer: SpeechStreamer) -> None:
    await until(lambda: not streamer.speaking)


async def test_a_spoken_delegation_plays_the_cached_phrase_first(executor) -> None:
    tts = FakeTts()
    cache = AckCache(PHRASES, lambda: tts, executor, "v")
    cache.warm()
    await until(lambda: cache.ready)
    streamer, stream = streamer_with(cache, executor, tts)
    try:
        synthesized = len(tts.sentences)
        streamer.acknowledge("m1", "voice")
        await until(lambda: any(t == "tts.chunk.meta" for t, _, _ in published(stream)))
        assert len(tts.sentences) == synthesized
        streamer.start(AssistantReply("Hecho.", "Hecho.", "voice", "m1"))
        await wait_quiet(streamer)
    finally:
        await streamer.aclose()

    events = published(stream)
    assert [t for t, _, _ in events] == [
        "tts.start",
        "tts.chunk.meta",
        "tts.chunk.meta",
        "tts.chunk.meta",
        "tts.chunk.meta",
        "tts.end",
    ]
    assert {m for _, m, _ in events} == {"m1"}
    metas = [p for t, _, p in events if t == "tts.chunk.meta"]
    assert [p["seq"] for p in metas] == [0, 1, 2, 3]
    assert [p["sentence_index"] for p in metas] == [0, 0, 1, 1]
    assert tts.sentences[-1] == "Hecho."
    assert streamer.spoken_text(["m1"]) == "Un momento, señor. Hecho."


@pytest.mark.parametrize("mode", ["text"])
async def test_no_acknowledgement_in_text_mode(executor, mode: str) -> None:
    tts = FakeTts()
    cache = AckCache(PHRASES, lambda: tts, executor, "v")
    cache.warm()
    await until(lambda: cache.ready)
    streamer, stream = streamer_with(cache, executor, tts)
    try:
        streamer.acknowledge("m1", mode)
        await asyncio.sleep(0.05)
    finally:
        await streamer.aclose()

    assert published(stream) == []


async def test_an_unready_cache_skips_the_acknowledgement_and_starts_warming(executor) -> None:
    tts = FakeTts()
    cache = AckCache(PHRASES, lambda: tts, executor, "v")
    streamer, stream = streamer_with(cache, executor, tts)
    try:
        streamer.acknowledge("m1", "both")
        await asyncio.sleep(0.02)
        assert published(stream) == []
        await until(lambda: cache.ready)
    finally:
        await streamer.aclose()


async def test_a_reply_that_already_has_audio_gets_no_acknowledgement(executor) -> None:
    tts = FakeTts()
    cache = AckCache(PHRASES, lambda: tts, executor, "v")
    cache.warm()
    await until(lambda: cache.ready)
    streamer, stream = streamer_with(cache, executor, tts)
    try:
        streamer.on_delta("m1", "Claro, señor. ")
        await until(lambda: any(t == "tts.chunk.meta" for t, _, _ in published(stream)))
        streamer.acknowledge("m1", "voice")
        streamer.start(AssistantReply("Claro, señor.", "Claro, señor.", "voice", "m1"))
        await wait_quiet(streamer)
    finally:
        await streamer.aclose()

    assert tts.sentences[len(PHRASES) :] == ["Claro,", "señor."]
    assert [t for t, _, _ in published(stream)].count("tts.chunk.meta") == 4
