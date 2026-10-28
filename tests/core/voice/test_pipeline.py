"""SpeechPipeline: sentences -> Tts -> SpeechSink, in order, cancellable (specs/voice-output)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest

from tests.fakes.sinks import ListEventSink
from tests.fakes.voice import FakeTts, ListSpeechSink
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.pipeline import TTS_EVENT, SpeechPipeline
from tony.core.voice.ports import AudioChunk, Tts

TWO_SENTENCES = "Son las diez. Tiene una reunión."


@pytest.fixture
def executor() -> Iterator[VoiceExecutor]:
    executor = VoiceExecutor()
    yield executor
    executor.close()


def pipeline(
    executor: VoiceExecutor, tts: Tts | None = None, loader=None
) -> tuple[SpeechPipeline, ListSpeechSink, ListEventSink]:
    sink, events = ListSpeechSink(), ListEventSink()
    tts = tts or FakeTts()
    return SpeechPipeline(loader or (lambda: tts), executor, "ef_dora", sink, events), sink, events


async def test_two_sentences_become_ordered_chunks_between_start_and_end(executor) -> None:
    tts = FakeTts()
    speech, sink, events = pipeline(executor, tts)

    speech.feed(TWO_SENTENCES)
    await speech.finish()

    assert sink.types() == ["start", "chunk", "chunk", "chunk", "chunk", "end"]
    assert [(seq, index) for seq, index, _ in sink.chunks] == [(0, 0), (1, 0), (2, 1), (3, 1)]
    assert tts.sentences == ["Son las diez.", "Tiene una reunión."]
    assert tts.voices == ["ef_dora", "ef_dora"]
    assert events.events == [(TTS_EVENT, {"sentences": 2, "duration_ms": 600, "cancelled": False})]


async def test_a_sentence_split_across_feeds_is_synthesized_whole(executor) -> None:
    tts = FakeTts()
    speech, sink, _ = pipeline(executor, tts)

    speech.feed("Son las ")
    speech.feed("diez. Tiene")
    speech.feed(" una reunión.")
    await speech.finish()

    assert tts.sentences == ["Son las diez.", "Tiene una reunión."]
    assert len(sink.chunks) == 4


async def test_finish_without_text_ends_without_starting(executor) -> None:
    speech, sink, events = pipeline(executor)

    await speech.finish()

    assert sink.types() == []
    assert events.events == [(TTS_EVENT, {"sentences": 0, "duration_ms": 0, "cancelled": False})]


class SlowTts(FakeTts):
    def __init__(self, delay_s: float = 0.05) -> None:
        super().__init__()
        self.delay_s = delay_s

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        time.sleep(self.delay_s)
        return super().synthesize(text, voice)


async def test_cancel_with_pending_sentences_emits_cancelled_and_nothing_more(executor) -> None:
    tts = SlowTts()
    speech, sink, events = pipeline(executor, tts)
    speech.feed("Una. Dos. Tres. Cuatro.")
    finishing = asyncio.ensure_future(speech.finish())
    while not sink.chunks:
        await asyncio.sleep(0.005)

    await speech.cancel()
    await finishing
    await asyncio.sleep(0.2)

    assert sink.types()[-1] == "cancelled"
    assert "end" not in sink.types()
    assert len(sink.chunks) < 8
    assert len(tts.sentences) < 4
    done = len(sink.chunks) // 2
    assert events.payloads(TTS_EVENT) == [
        {"sentences": done, "duration_ms": done * 300, "cancelled": True}
    ]


async def test_cancel_is_idempotent_and_a_no_op_after_the_end(executor) -> None:
    speech, sink, events = pipeline(executor)
    speech.feed("Una.")
    await speech.finish()

    await speech.cancel()
    await speech.cancel()

    assert sink.types() == ["start", "chunk", "chunk", "end"]
    assert len(events.events) == 1

    fresh, fresh_sink, fresh_events = pipeline(executor)
    await fresh.cancel()
    await fresh.cancel()
    assert fresh_sink.types() == ["cancelled"]
    assert fresh_events.payloads(TTS_EVENT) == [
        {"sentences": 0, "duration_ms": 0, "cancelled": True}
    ]


async def test_failure_in_the_second_sentence_degrades_after_the_first(executor) -> None:
    speech, sink, events = pipeline(executor, FakeTts(fail_at_sentence=2))

    speech.feed("Una. Dos. Tres.")
    await speech.finish()

    assert sink.types() == ["start", "chunk", "chunk", "failed", "cancelled"]
    assert "frase 2" in sink.failures[0]
    assert events.payloads(TTS_EVENT) == [{"sentences": 1, "duration_ms": 300, "cancelled": True}]


async def test_a_loader_that_raises_fails_without_start(executor) -> None:
    def broken() -> Tts:
        raise RuntimeError("espeak-ng no encontrado")

    speech, sink, events = pipeline(executor, loader=broken)
    speech.feed("Una. Dos.")
    await speech.finish()

    assert sink.types() == ["failed"]
    assert sink.failures == ["RuntimeError: espeak-ng no encontrado"]
    assert events.payloads(TTS_EVENT) == [{"sentences": 0, "duration_ms": 0, "cancelled": True}]


async def test_sentences_never_synthesize_concurrently(executor) -> None:
    tts = SlowTts(delay_s=0.01)
    speech, sink, _ = pipeline(executor, tts)

    speech.feed("Una. Dos. Tres. Cuatro. Cinco.")
    await speech.finish()

    assert tts.peak_running == 1
    assert [index for _, index, _ in sink.chunks] == [i // 2 for i in range(10)]
    assert [seq for seq, _, _ in sink.chunks] == list(range(10))
