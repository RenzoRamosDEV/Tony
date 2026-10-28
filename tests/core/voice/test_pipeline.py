"""SpeechPipeline: sentences -> Tts -> SpeechSink, in order, cancellable (specs/voice-output)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

import pytest

from tests.fakes.sinks import ListEventSink
from tests.fakes.voice import FakeTts, ListSpeechSink, sine_chunk
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.pipeline import TTS_EVENT, SpeechPipeline
from tony.core.voice.ports import AudioChunk, Tts
from tony.core.voice.segmenter import SentenceSegmenter

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
    assert events.events == [(TTS_EVENT, {"sentences": 2, "duration_ms": 760, "cancelled": False})]


SAMPLE_BYTES = 2
PAUSE_SAMPLES = {"sentence": 3_840, "clause": 1_920}


def trailing_zero_samples(chunk: AudioChunk) -> int:
    pcm = chunk.pcm16
    count = 0
    while (
        count * SAMPLE_BYTES < len(pcm)
        and pcm[len(pcm) - (count + 1) * SAMPLE_BYTES :][:SAMPLE_BYTES] == b"\0\0"
    ):
        count += 1
    return count


async def test_a_sentence_ends_with_160ms_of_silence_and_the_last_piece_with_none(
    executor,
) -> None:
    speech, sink, _ = pipeline(executor)

    speech.feed(TWO_SENTENCES)
    await speech.finish()

    chunks = [chunk for _, _, chunk in sink.chunks]
    assert trailing_zero_samples(chunks[1]) == PAUSE_SAMPLES["sentence"]
    assert len(chunks[1].pcm16) == len(sine_chunk().pcm16) + 3_840 * SAMPLE_BYTES
    assert trailing_zero_samples(chunks[0]) < 10
    assert chunks[3] == sine_chunk()


async def test_a_first_clause_ends_with_80ms_of_silence(executor) -> None:
    sink, events = ListSpeechSink(), ListEventSink()
    tts = FakeTts()
    speech = SpeechPipeline(
        lambda: tts, executor, "v", sink, events, segmenter=SentenceSegmenter(first_clause=True)
    )

    speech.feed("Buenas tardes, señor.")
    await speech.finish()

    chunks = [chunk for _, _, chunk in sink.chunks]
    assert tts.sentences == ["Buenas tardes,", "señor."]
    assert trailing_zero_samples(chunks[1]) == PAUSE_SAMPLES["clause"]
    assert chunks[3] == sine_chunk()
    assert events.events[-1][1]["duration_ms"] == 4 * 150 + 80


async def test_redaction_still_covers_a_secret_split_across_feeds(executor) -> None:
    sink, events = ListSpeechSink(), ListEventSink()
    tts = FakeTts()
    speech = SpeechPipeline(
        lambda: tts,
        executor,
        "v",
        sink,
        events,
        segmenter=SentenceSegmenter(first_clause=True),
        sanitize=lambda text: text.replace("sk-123456", "[oculto]"),
    )

    for fragment in ("La clave sk-12", "3456 está guardada. Nada más."):
        speech.feed(fragment)
    await speech.finish()

    assert all("sk-" not in sentence for sentence in tts.sentences)
    assert "[oculto]" in " ".join(tts.sentences)


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
        {"sentences": done, "duration_ms": done * (300 + 160), "cancelled": True}
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
    assert events.payloads(TTS_EVENT) == [
        {"sentences": 1, "duration_ms": 300 + 160, "cancelled": True}
    ]


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


class BlockingTts(FakeTts):
    """Blocks inside `synthesize` until `release`, like a native inference that ignores cancel."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.log: list[str] = []

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        self.log.append(f"enter {text}")
        self.entered.set()
        self.gate.wait(timeout=5)
        self.log.append(f"exit {text}")
        return super().synthesize(text, voice)


async def test_review05_finding_7_next_synthesis_waits_for_the_cancelled_one_to_return(
    executor,
) -> None:
    tts = BlockingTts()
    first, _, _ = pipeline(executor, tts)
    second, second_sink, _ = pipeline(executor, tts)

    first.feed("Primera frase.")
    finishing = asyncio.ensure_future(first.finish())
    await asyncio.get_running_loop().run_in_executor(None, tts.entered.wait)
    await first.cancel()
    await asyncio.gather(finishing, return_exceptions=True)
    second.feed("Segunda frase.")
    done = asyncio.ensure_future(second.finish())
    await asyncio.sleep(0.05)
    before_release = list(tts.log)
    tts.gate.set()
    await asyncio.wait_for(done, 2)

    assert before_release == ["enter Primera frase."]
    assert tts.log == [
        "enter Primera frase.",
        "exit Primera frase.",
        "enter Segunda frase.",
        "exit Segunda frase.",
    ]
    assert second_sink.types()[-1] == "end"


class CountingTts(FakeTts):
    def __init__(self) -> None:
        super().__init__()
        self.pulled = 0

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        self.sentences.append(text)
        for _ in range(3):
            self.pulled += 1
            yield sine_chunk()


async def test_review05_finding_7_a_stopped_pipeline_pulls_no_chunk_at_all(executor) -> None:
    tts = CountingTts()
    speech, _, _ = pipeline(executor, tts)

    speech._stop.set()
    chunks = await executor.run(speech._synthesize, tts, "Una frase.")

    assert chunks == [] and tts.pulled == 0


def test_with_pause_extends_only_the_last_chunk_at_its_own_rate() -> None:
    from tony.core.voice.pipeline import with_pause

    chunks = [
        AudioChunk(b"\x01\x00", 16_000),
        AudioChunk(b"\x02\x00", 16_000),
        AudioChunk(b"\x03\x00", 16_000),
    ]

    paused = with_pause(chunks, "clause")

    assert paused[:2] == chunks[:2]
    assert paused[2] == AudioChunk(b"\x03\x00" + b"\0" * (16_000 * 80 // 1_000 * 2), 16_000)
    assert with_pause(chunks, "final") == chunks
    assert with_pause([], "sentence") == []


class SilentTts(FakeTts):
    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        self.sentences.append(text)
        return iter(())


async def test_pieces_without_audio_get_no_pause_and_end_cleanly(executor) -> None:
    speech, sink, events = pipeline(executor, SilentTts())

    speech.feed(TWO_SENTENCES)
    await speech.finish()

    assert sink.types() == ["start", "end"]
    assert events.payloads(TTS_EVENT) == [{"sentences": 2, "duration_ms": 0, "cancelled": False}]
