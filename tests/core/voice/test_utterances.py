"""UtteranceAssembler: 500 ms end-of-speech, 300 ms minimum, 30 s cut (specs/voice-engines)."""

from __future__ import annotations

from array import array

import pytest

from tony.core.voice.ports import VAD_WINDOW_SAMPLES, Vad
from tony.core.voice.utterances import UtteranceAssembler, VadSegmenter

WINDOW_MS = 32
SPEECH = array("f", [0.5] * VAD_WINDOW_SAMPLES).tobytes()
SILENCE = array("f", [0.0] * VAD_WINDOW_SAMPLES).tobytes()


def windows(duration_ms: int) -> int:
    return -(-duration_ms // WINDOW_MS)


def push(assembler: UtteranceAssembler, speech_ms: int = 0, silence_ms: int = 0) -> list:
    emitted = []
    for _ in range(windows(speech_ms)):
        emitted += assembler.push(SPEECH, True)
    for _ in range(windows(silence_ms)):
        emitted += assembler.push(SILENCE, False)
    return emitted


def test_500ms_of_silence_after_speech_closes_the_utterance_by_default() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    none_yet = push(assembler, speech_ms=1_500, silence_ms=500 - WINDOW_MS)
    closed = assembler.push(SILENCE, False)

    assert none_yet == []
    assert len(closed) == 1
    assert closed[0].duration_ms == windows(1_500) * WINDOW_MS
    assert closed[0].pcm == SPEECH * windows(1_500)
    assert assembler.pending_ms == 0


def test_speech_shorter_than_300ms_is_discarded() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    assert push(assembler, speech_ms=200, silence_ms=1_000) == []
    assert assembler.pending_ms == 0


def test_exactly_300ms_of_speech_is_kept() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, min_speech_ms=320)

    assert len(push(assembler, speech_ms=320, silence_ms=500)) == 1


def test_silence_shorter_than_500ms_does_not_close() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    assert push(assembler, speech_ms=1_000, silence_ms=400) == []
    assert push(assembler, speech_ms=1_000) == []
    assert assembler.pending_ms == windows(1_000) * 2 * WINDOW_MS + windows(400) * WINDOW_MS
    closed = push(assembler, silence_ms=500)
    assert len(closed) == 1
    assert closed[0].duration_ms == assembler_total(1_000, 400, 1_000)


@pytest.mark.parametrize(("silence_ms", "count"), [(468, 0), (500, 1)])
def test_default_end_silence_boundary(silence_ms: int, count: int) -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    assert len(push(assembler, speech_ms=1_000, silence_ms=silence_ms)) == count


def test_configured_end_silence_of_700ms_waits_past_600ms() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, end_silence_ms=700)

    assert push(assembler, speech_ms=1_000, silence_ms=600) == []
    assert len(push(assembler, silence_ms=100)) == 1


def test_two_speech_windows_separated_by_ten_silent_ones_are_discarded() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    emitted = assembler.push(SPEECH, True)
    emitted += [u for _ in range(10) for u in assembler.push(SILENCE, False)]
    emitted += assembler.push(SPEECH, True)
    emitted += push(assembler, silence_ms=500)

    assert emitted == []


def test_speech_ms_counts_the_speech_of_the_open_utterance() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    push(assembler, speech_ms=5 * WINDOW_MS, silence_ms=2 * WINDOW_MS)
    assembler.push(SPEECH, True)
    assert assembler.speech_ms == 6 * WINDOW_MS
    push(assembler, silence_ms=500)
    assert assembler.speech_ms == 0


def assembler_total(*parts_ms: int) -> int:
    return sum(windows(part) for part in parts_ms) * WINDOW_MS


def test_30s_of_continuous_speech_is_cut_and_the_rest_starts_anew() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    emitted = push(assembler, speech_ms=31_000)

    assert len(emitted) == 1
    assert 30_000 <= emitted[0].duration_ms < 30_000 + WINDOW_MS
    assert assembler.pending_ms == windows(31_000) * WINDOW_MS - emitted[0].duration_ms
    assert assembler.pending_ms > 0


@pytest.mark.parametrize(("silence_windows", "count"), [(9, 0), (10, 1)])
def test_end_silence_closes_exactly_at_the_threshold(silence_windows: int, count: int) -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, end_silence_ms=10 * WINDOW_MS)
    push(assembler, speech_ms=1_000)

    emitted = [u for _ in range(silence_windows) for u in assembler.push(SILENCE, False)]

    assert len(emitted) == count


@pytest.mark.parametrize(("speech_windows", "count"), [(9, 0), (10, 1)])
def test_forced_cut_happens_exactly_at_the_maximum(speech_windows: int, count: int) -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, max_utterance_ms=10 * WINDOW_MS)

    emitted = [u for _ in range(speech_windows) for u in assembler.push(SPEECH, True)]

    assert len(emitted) == count
    if emitted:
        assert emitted[0].duration_ms == 10 * WINDOW_MS and assembler.pending_ms == 0


@pytest.mark.parametrize(("silence_windows", "count"), [(9, 0), (10, 1)])
def test_the_silence_counter_starts_from_zero_after_speech(
    silence_windows: int, count: int
) -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, end_silence_ms=9 * WINDOW_MS + 1)
    push(assembler, speech_ms=1_000)

    emitted = [u for _ in range(silence_windows) for u in assembler.push(SILENCE, False)]

    assert len(emitted) == count


def test_counters_restart_after_an_utterance_closes() -> None:
    threshold = 9 * WINDOW_MS + 1
    assembler = UtteranceAssembler(
        window_ms=WINDOW_MS, end_silence_ms=threshold, min_speech_ms=10 * WINDOW_MS
    )
    first = [u for _ in range(10) for u in assembler.push(SPEECH, True)]
    first += [u for _ in range(10) for u in assembler.push(SILENCE, False)]
    assert len(first) == 1

    nine_speech = [u for _ in range(9) for u in assembler.push(SPEECH, True)]
    nine_silence = [u for _ in range(9) for u in assembler.push(SILENCE, False)]
    tenth_silence = assembler.push(SILENCE, False)

    assert nine_speech == [] and nine_silence == []
    assert tenth_silence == []
    assert assembler.pending_ms == 0


def test_consecutive_utterances_have_independent_durations() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    first = push(assembler, speech_ms=1_000, silence_ms=500)
    second = push(assembler, speech_ms=500, silence_ms=500)
    none = push(assembler, speech_ms=100, silence_ms=500)

    assert [u.duration_ms for u in first] == [windows(1_000) * WINDOW_MS]
    assert [u.duration_ms for u in second] == [windows(500) * WINDOW_MS]
    assert second[0].pcm == SPEECH * windows(500)
    assert none == [] and assembler.pending_ms == 0


def test_leading_silence_is_never_buffered() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    push(assembler, silence_ms=2_000)

    assert assembler.pending_ms == 0


@pytest.mark.parametrize(("speech_ms", "count"), [(1_000, 1), (200, 0), (0, 0)])
def test_flush_emits_only_enough_pending_speech(speech_ms: int, count: int) -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)
    push(assembler, speech_ms=speech_ms, silence_ms=200)

    flushed = assembler.flush()

    assert len(flushed) == count
    assert assembler.pending_ms == 0
    if flushed:
        assert flushed[0].duration_ms == windows(speech_ms) * WINDOW_MS


class AlwaysSpeech:
    def __init__(self) -> None:
        self.windows: list[bytes] = []
        self.resets = 0

    def classify(self, window: bytes, threshold: float) -> bool:
        self.windows.append(window)
        return True

    def reset(self) -> None:
        self.resets += 1


def test_segmenter_cuts_the_pcm_into_512_sample_windows_and_resets_per_utterance() -> None:
    vad = AlwaysSpeech()
    assert isinstance(vad, Vad)
    segmenter = VadSegmenter(vad, UtteranceAssembler(window_ms=WINDOW_MS))
    samples = array("f", [0.1] * (VAD_WINDOW_SAMPLES * 10 + 100)).tobytes()

    assert segmenter.feed(samples) == []
    assert vad.windows == [samples[i * 2048 : (i + 1) * 2048] for i in range(10)]
    flushed = segmenter.flush()

    assert len(flushed) == 1 and flushed[0].duration_ms == 10 * WINDOW_MS
    assert vad.resets == 1


def test_segmenter_feeds_exact_windows_and_forgets_the_remainder_on_flush() -> None:
    vad = AlwaysSpeech()
    segmenter = VadSegmenter(vad, UtteranceAssembler(window_ms=WINDOW_MS, min_speech_ms=0))
    exact = array("f", [0.2] * VAD_WINDOW_SAMPLES).tobytes()
    partial = array("f", [0.3] * 100).tobytes()

    segmenter.feed(exact)
    assert vad.windows == [exact]
    segmenter.feed(partial)
    segmenter.flush()
    segmenter.feed(exact)

    assert vad.windows == [exact, exact]


class EnergyVad:
    def classify(self, window: bytes, threshold: float) -> bool:
        return window[:4] != b"\0\0\0\0"

    def reset(self) -> None:
        return None


def test_two_utterances_in_one_feed_are_both_returned() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, end_silence_ms=64, min_speech_ms=64)
    segmenter = VadSegmenter(EnergyVad(), assembler)
    pcm = SPEECH * 3 + SILENCE * 2 + SPEECH * 4 + SILENCE * 2

    utterances = segmenter.feed(pcm)

    assert [u.duration_ms for u in utterances] == [3 * WINDOW_MS, 4 * WINDOW_MS]


def test_review05_finding_13_minimum_counts_speech_windows_not_inner_silence() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)

    emitted = assembler.push(SPEECH, True)
    for _ in range(20):
        emitted += assembler.push(SILENCE, False)
    emitted += assembler.push(SPEECH, True)
    emitted += assembler.flush()

    assert emitted == []


def test_review05_finding_13_maximum_counts_the_total_duration_including_inner_silence() -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS, max_utterance_ms=30_000)
    emitted: list = []
    pushed = 0

    while not emitted and pushed < 2_000:
        emitted += assembler.push(SPEECH, pushed % 2 == 0)
        pushed += 1

    assert len(emitted) == 1
    assert pushed == windows(30_000)
    assert emitted[0].duration_ms <= 30_000


class SpyVad:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def classify(self, window: bytes, threshold: float) -> bool:
        self.calls.append("classify")
        return True

    def reset(self) -> None:
        self.calls.append("reset")


def test_review05_finding_14_reset_forgets_the_partial_utterance_and_resets_the_vad() -> None:
    vad = SpyVad()
    segmenter = VadSegmenter(vad)

    segmenter.feed(SPEECH * 3 + SPEECH[:100])
    segmenter.reset()
    after = segmenter.flush()

    assert vad.calls[:4] == ["classify"] * 3 + ["reset"]
    assert after == []


def test_review05_finding_14_reset_drops_the_remainder_of_a_partial_window() -> None:
    windows: list[bytes] = []

    class Recording(SpyVad):
        def classify(self, window: bytes, threshold: float) -> bool:
            windows.append(window)
            return True

    segmenter = VadSegmenter(Recording())
    segmenter.feed(SILENCE[:100])
    segmenter.reset()
    segmenter.feed(SPEECH)

    assert windows == [SPEECH]


@pytest.mark.parametrize(("speech_windows", "count"), [(9, 0), (10, 1)])
def test_review05_finding_13_minimum_speech_boundary_on_a_fresh_assembler(
    speech_windows: int, count: int
) -> None:
    assembler = UtteranceAssembler(window_ms=WINDOW_MS)
    for _ in range(speech_windows):
        assembler.push(SPEECH, True)

    assert len(assembler.flush()) == count


class ThresholdSpy:
    def __init__(self) -> None:
        self.thresholds: list[float] = []

    def classify(self, window: bytes, threshold: float) -> bool:
        self.thresholds.append(threshold)
        return False

    def reset(self) -> None:
        return None


def test_segmenter_forwards_the_threshold_to_every_window() -> None:
    vad = ThresholdSpy()
    segmenter = VadSegmenter(vad)

    segmenter.feed(SILENCE * 2, 0.8)
    segmenter.feed(SILENCE)

    assert vad.thresholds == [0.8, 0.8, 0.5]
    assert segmenter.speech_ms == 0
