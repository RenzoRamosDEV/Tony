"""AudioSession budgets and ordering: bounded backlog, VAD off the loop, VAD reset per capture."""

from __future__ import annotations

import asyncio
import threading
import time
from array import array
from collections.abc import Iterator

import pytest

from tests.fakes.sinks import ListEventSink
from tests.fakes.voice import FakeStt, FakeVad
from tony.apps.web.audio_ws import AUDIO_BACKPRESSURE, AudioSession
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.ports import INPUT_SAMPLE_RATE, Transcript, Utterance

FRAME_SAMPLES = 4_096


def pcm(value: float, duration_ms: int) -> bytes:
    return array("f", [value] * (INPUT_SAMPLE_RATE * duration_ms // 1_000)).tobytes()


ONE_UTTERANCE = pcm(0.5, 512) + pcm(0.0, 768)


def frames(data: bytes) -> list[bytes]:
    size = FRAME_SAMPLES * 4
    return [data[i : i + size] for i in range(0, len(data), size)]


class GatedStt(FakeStt):
    def __init__(self) -> None:
        super().__init__("hola")
        self.gate = threading.Event()

    def transcribe(self, utterance: Utterance, language: str) -> Transcript:
        self.gate.wait(timeout=5)
        return super().transcribe(utterance, language)


class SlowVad(FakeVad):
    def classify(self, window: bytes, threshold: float) -> bool:
        time.sleep(0.005)
        return super().classify(window, threshold)


class Recorder:
    def __init__(self) -> None:
        self.finals: list[str] = []
        self.errors: list[str] = []
        self.details: list[str] = []

    async def on_final(self, transcript: Transcript) -> None:
        self.finals.append(transcript.text)

    async def on_error(self, code: str, detail: str) -> None:
        self.errors.append(code)
        self.details.append(detail)


@pytest.fixture
def executor() -> Iterator[VoiceExecutor]:
    executor = VoiceExecutor()
    yield executor
    executor.close()


def session(executor: VoiceExecutor, vad, stt, recorder: Recorder, **budget) -> AudioSession:
    return AudioSession(
        vad,
        lambda: stt,
        executor,
        "es",
        recorder.on_final,
        recorder.on_error,
        ListEventSink(),
        **budget,
    )


async def wait_for(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


async def test_review05_finding_3_at_most_two_utterances_wait_for_stt_the_rest_is_dropped(
    executor,
) -> None:
    stt, recorder = GatedStt(), Recorder()
    audio = session(executor, FakeVad(), stt, recorder)
    audio.open()
    try:
        for _ in range(4):
            for frame in frames(ONE_UTTERANCE):
                assert audio.feed(frame)
        await wait_for(lambda: len(recorder.errors) == 2)
        stt.gate.set()
        await wait_for(lambda: len(recorder.finals) == 2)
        await asyncio.sleep(0.05)
    finally:
        await audio.aclose()

    assert recorder.errors == [AUDIO_BACKPRESSURE, AUDIO_BACKPRESSURE]
    assert len(stt.calls) == 2


async def test_review05_finding_3_pending_pcm_beyond_the_budget_is_refused(executor) -> None:
    stt, recorder = GatedStt(), Recorder()
    audio = session(executor, SlowVad(), stt, recorder, max_pending_samples=3 * FRAME_SAMPLES)
    audio.open()
    try:
        accepted = [audio.feed(pcm(0.5, 256)) for _ in range(5)]
    finally:
        stt.gate.set()
        await audio.aclose()

    assert accepted == [True, True, True, False, False]


async def test_review05_finding_4_the_loop_keeps_running_while_the_vad_classifies(
    executor,
) -> None:
    recorder = Recorder()
    audio = session(executor, SlowVad(), FakeStt("hola"), recorder)
    audio.open()
    ticks = 0

    async def timer() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    ticking = asyncio.ensure_future(timer())
    try:
        started = time.monotonic()
        for frame in frames(ONE_UTTERANCE):
            audio.feed(frame)
        fed_in = time.monotonic() - started
        await wait_for(lambda: recorder.finals == ["hola"])
    finally:
        ticking.cancel()
        await audio.aclose()

    assert fed_in < 0.05
    assert ticks >= 5


class SpyVad(FakeVad):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def classify(self, window: bytes, threshold: float) -> bool:
        self.calls.append("classify")
        return super().classify(window, threshold)

    def reset(self) -> None:
        self.calls.append("reset")


async def test_review05_finding_14_every_new_capture_resets_the_shared_vad_first(
    executor,
) -> None:
    vad, recorder = SpyVad(), Recorder()
    first = session(executor, vad, FakeStt("hola"), recorder)
    first.open()
    first.feed(pcm(0.5, 128))
    await wait_for(lambda: vad.calls.count("classify") == 4)
    first.discard()
    second = session(executor, vad, FakeStt("hola"), recorder)
    second.open()
    second.feed(pcm(0.5, 64))
    await wait_for(lambda: vad.calls.count("classify") == 6)
    await second.aclose()

    assert vad.calls == ["reset"] + ["classify"] * 4 + ["reset"] + ["classify"] * 2


class CountingVad(FakeVad):
    def __init__(self, fail_first: bool = False) -> None:
        super().__init__()
        self.classified = 0
        self.fail_first = fail_first

    def classify(self, window: bytes, threshold: float) -> bool:
        self.classified += 1
        if self.fail_first and self.classified == 1:
            raise RuntimeError("vad roto")
        return super().classify(window, threshold)


SPEECH_SAMPLES = 8_192


async def feed_slowly(audio: AudioSession, vad: CountingVad, data: bytes) -> None:
    """One frame at a time, each fully classified before the next, so no frame is pending."""
    for frame in frames(data):
        before = vad.classified
        assert audio.feed(frame)
        windows = len(frame) // (512 * 4)
        if windows:
            await wait_for(
                lambda before=before, windows=windows: vad.classified >= before + windows
            )
        await asyncio.sleep(0.01)


async def test_review05_finding_3_the_budget_is_released_after_each_transcription(
    executor,
) -> None:
    vad, stt, recorder = CountingVad(), FakeStt("hola"), Recorder()
    audio = session(executor, vad, stt, recorder, max_pending_samples=SPEECH_SAMPLES)
    audio.open()
    try:
        for done in range(1, 4):
            await feed_slowly(audio, vad, ONE_UTTERANCE)
            await wait_for(lambda done=done: len(recorder.finals) == done)
    finally:
        await audio.aclose()

    assert recorder.errors == []
    assert [language for _, language in stt.calls] == ["es", "es", "es"]


async def test_review05_finding_3_an_utterance_beyond_the_sample_budget_is_dropped(
    executor,
) -> None:
    vad, stt, recorder = CountingVad(), GatedStt(), Recorder()
    audio = session(
        executor,
        vad,
        stt,
        recorder,
        max_pending_samples=SPEECH_SAMPLES + FRAME_SAMPLES,
        max_pending_utterances=10,
    )
    audio.open()
    try:
        await feed_slowly(audio, vad, ONE_UTTERANCE)
        await feed_slowly(audio, vad, ONE_UTTERANCE)
        await wait_for(lambda: recorder.errors == [AUDIO_BACKPRESSURE])
        stt.gate.set()
        await wait_for(lambda: recorder.finals == ["hola"])
    finally:
        stt.gate.set()
        await audio.aclose()

    assert recorder.details[0].startswith("hay demasiadas intervenciones")


async def test_review05_finding_4_engine_failures_are_reported_and_the_budget_released(
    executor,
) -> None:
    vad, recorder = CountingVad(fail_first=True), Recorder()
    stt = FakeStt("hola", fail=True)
    audio = session(executor, vad, stt, recorder, max_pending_samples=SPEECH_SAMPLES)
    audio.open()
    try:
        assert audio.feed(pcm(0.5, 256))
        await wait_for(lambda: len(recorder.errors) == 1)
        await feed_slowly(audio, vad, ONE_UTTERANCE)
        await wait_for(lambda: len(recorder.errors) == 2)
        stt.fail = False
        await feed_slowly(audio, vad, ONE_UTTERANCE)
        await wait_for(lambda: recorder.finals == ["hola"])
    finally:
        await audio.aclose()

    assert recorder.errors == ["stt_failed", "stt_failed"]
    assert recorder.details == [
        "RuntimeError: vad roto",
        "RuntimeError: el transcriptor falló",
    ]


async def test_review05_finding_3_capturing_follows_open_end_and_discard(executor) -> None:
    audio = session(executor, FakeVad(), FakeStt("hola"), Recorder())
    states = [audio.capturing]
    audio.discard()
    audio.open()
    states.append(audio.capturing)
    audio.end()
    states.append(audio.capturing)
    audio.open()
    audio.discard()
    states.append(audio.capturing)
    await audio.aclose()

    assert states == [False, True, False, False]


async def test_review05_finding_3_the_sample_budget_counts_every_waiting_utterance(
    executor,
) -> None:
    vad, stt, recorder = CountingVad(), GatedStt(), Recorder()
    audio = session(
        executor,
        vad,
        stt,
        recorder,
        max_pending_samples=2 * SPEECH_SAMPLES + FRAME_SAMPLES,
        max_pending_utterances=10,
    )
    audio.open()
    try:
        for _ in range(3):
            await feed_slowly(audio, vad, ONE_UTTERANCE)
        await wait_for(lambda: recorder.errors == [AUDIO_BACKPRESSURE])
        stt.gate.set()
        await wait_for(lambda: len(recorder.finals) == 2)
        await asyncio.sleep(0.05)
    finally:
        stt.gate.set()
        await audio.aclose()

    assert len(stt.calls) == 2


async def test_review05_finding_3_the_utterance_limit_recovers_after_each_transcription(
    executor,
) -> None:
    vad, stt, recorder = CountingVad(), GatedStt(), Recorder()
    stt.gate.set()
    audio = session(executor, vad, stt, recorder)
    audio.open()
    try:
        await feed_slowly(audio, vad, ONE_UTTERANCE)
        await wait_for(lambda: len(recorder.finals) == 1)
        stt.gate.clear()
        for _ in range(4):
            await feed_slowly(audio, vad, ONE_UTTERANCE)
        await wait_for(lambda: len(recorder.errors) >= 2)
        await asyncio.sleep(0.05)
        stt.gate.set()
        await wait_for(lambda: len(recorder.finals) == 3)
    finally:
        stt.gate.set()
        await audio.aclose()

    assert recorder.errors == [AUDIO_BACKPRESSURE, AUDIO_BACKPRESSURE]
