import asyncio
import threading
import time

import pytest

from tony.core.voice.timing import (
    MARKS,
    LoopLagSampler,
    NullTimings,
    StageTimings,
    format_report,
    percentile,
    summarise,
)


class Ticking:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def record_turn(timings: StageTimings, start: float, latency: float) -> None:
    turn = timings.begin_turn()
    timings.mark(turn, "speech_end", start)
    timings.mark(turn, "capture_close", start + 0.1 * latency)
    timings.mark(turn, "stt_end", start + 0.4 * latency)
    timings.mark(turn, "first_token", start + 0.6 * latency)
    timings.mark(turn, "playback_start", start + latency)


def test_marks_are_stored_in_order_with_the_clock_time():
    timings = StageTimings(clock=Ticking())
    turn = timings.begin_turn()
    timings.mark(turn, "speech_end")
    timings.mark(turn, "capture_close")
    assert timings.turns() == {turn: {"speech_end": 1.0, "capture_close": 2.0}}


def test_an_explicit_timestamp_overrides_the_clock():
    timings = StageTimings(clock=Ticking())
    turn = timings.begin_turn()
    timings.mark(turn, "speech_end", 0.25)
    assert timings.turns()[turn] == {"speech_end": 0.25}


def test_only_the_first_mark_of_a_name_is_kept():
    timings = StageTimings(clock=Ticking())
    turn = timings.begin_turn()
    timings.mark(turn, "synthesis_start")
    timings.mark(turn, "synthesis_start")
    assert timings.turns()[turn] == {"synthesis_start": 1.0}


def test_turn_ids_are_distinct():
    timings = StageTimings()
    assert timings.begin_turn() != timings.begin_turn()


def test_marks_without_a_turn_are_ignored():
    timings = StageTimings()
    timings.mark(None, "speech_end")
    assert timings.turns() == {}


def test_null_recorder_does_nothing():
    timings = NullTimings()
    assert timings.begin_turn() is None
    timings.mark(None, "speech_end")
    timings.mark(3, "playback_start", 1.0)
    assert timings.turns() == {}
    assert timings.now() == 0.0


def test_the_eight_marks_are_defined():
    assert len(MARKS) == 8


def test_unknown_mark_names_are_rejected():
    timings = StageTimings()
    turn = timings.begin_turn()
    with pytest.raises(ValueError):
        timings.mark(turn, "what the user said")


@pytest.mark.parametrize("value", ["hello", "1.5", b"\x00\x01"])
def test_timestamps_cannot_carry_text_or_audio(value):
    timings = StageTimings()
    turn = timings.begin_turn()
    with pytest.raises((TypeError, ValueError)):
        timings.mark(turn, "speech_end", value)
    assert timings.turns().get(turn, {}) == {}


def test_concurrent_marking_loses_nothing():
    timings = StageTimings()
    turns = [timings.begin_turn() for _ in range(8)]

    def worker(name: str) -> None:
        for turn in turns:
            timings.mark(turn, name)

    threads = [threading.Thread(target=worker, args=(name,)) for name in MARKS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(set(marks) == set(MARKS) for marks in timings.turns().values())
    assert len(timings.turns()) == 8


def test_concurrent_turn_ids_are_unique():
    timings = StageTimings()
    ids: list[int] = []
    threads = [
        threading.Thread(target=lambda: ids.extend(timings.begin_turn() for _ in range(50)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(ids)) == 200


@pytest.mark.parametrize(
    ("values", "fraction", "expected"),
    [
        (list(range(1, 21)), 0.5, 10.5),
        (list(range(1, 21)), 0.95, 19.05),
        ([7.0], 0.95, 7.0),
        ([3.0, 1.0, 2.0], 0.0, 1.0),
        ([3.0, 1.0, 2.0], 1.0, 3.0),
    ],
)
def test_percentile_interpolates_linearly(values, fraction, expected):
    assert percentile(values, fraction) == pytest.approx(expected)


def test_percentile_of_nothing_is_none():
    assert percentile([], 0.5) is None


def test_report_percentiles_over_twenty_warm_turns():
    timings = StageTimings()
    record_turn(timings, 0.0, 99.0)
    for latency in range(1, 21):
        record_turn(timings, 1000.0 * latency, float(latency))
    report = summarise(timings)

    assert report.warm.count == 20
    assert report.warm.intervals["end_to_end"].p50 == pytest.approx(10.5)
    assert report.warm.intervals["end_to_end"].p95 == pytest.approx(19.05)


def test_report_splits_cold_from_warm():
    timings = StageTimings()
    record_turn(timings, 0.0, 9.0)
    record_turn(timings, 100.0, 1.0)
    record_turn(timings, 200.0, 3.0)
    report = summarise(timings)

    assert report.cold.count == 1
    assert report.cold.intervals["end_to_end"].p50 == pytest.approx(9.0)
    assert report.warm.count == 2
    assert report.warm.intervals["end_to_end"].p50 == pytest.approx(2.0)


def test_report_has_every_interval():
    timings = StageTimings()
    record_turn(timings, 0.0, 10.0)
    intervals = summarise(timings).cold.intervals
    assert {name: round(stat.p50, 6) for name, stat in intervals.items()} == {
        "endpointing": 1.0,
        "transcription": 3.0,
        "reply_start": 2.0,
        "first_token_to_playback": 4.0,
        "end_to_end": 10.0,
    }


def test_no_p95_below_twenty_samples():
    timings = StageTimings()
    record_turn(timings, 0.0, 1.0)
    for index in range(5):
        record_turn(timings, 100.0 * (index + 1), 1.0)
    report = summarise(timings)
    assert report.warm.count == 5
    assert report.warm.intervals["end_to_end"].p95 is None
    assert report.cold.intervals["end_to_end"].p95 is None


def test_no_p95_at_nineteen_samples():
    timings = StageTimings()
    for index in range(20):
        record_turn(timings, 100.0 * index, 1.0)
    report = summarise(timings)
    assert report.warm.count == 19
    assert report.warm.intervals["end_to_end"].p95 is None


def test_p95_appears_at_exactly_twenty_samples():
    timings = StageTimings()
    for index in range(21):
        record_turn(timings, 100.0 * index, 1.0)
    assert summarise(timings).warm.intervals["end_to_end"].p95 is not None


def test_incomplete_turns_are_not_counted():
    timings = StageTimings()
    turn = timings.begin_turn()
    timings.mark(turn, "speech_end", 0.0)
    record_turn(timings, 10.0, 1.0)
    report = summarise(timings)
    assert report.cold.count == 1
    assert report.warm.count == 0


def test_empty_report_has_no_stats():
    report = summarise(StageTimings())
    assert report.cold.count == 0
    assert report.warm.intervals == {}


def test_turns_are_ordered_by_speech_end_not_by_id():
    timings = StageTimings()
    later, earlier = timings.begin_turn(), timings.begin_turn()
    for turn, start, end in ((later, 50.0, 51.0), (earlier, 5.0, 100.0)):
        timings.mark(turn, "speech_end", start)
        timings.mark(turn, "playback_start", end)
    assert summarise(timings).cold.intervals["end_to_end"].p50 == pytest.approx(95.0)


def test_format_report_states_counts_and_omits_missing_p95():
    timings = StageTimings()
    record_turn(timings, 0.0, 2.0)
    record_turn(timings, 10.0, 1.0)
    text = format_report(summarise(timings))
    assert "cold (n=1)" in text
    assert "warm (n=1)" in text
    assert "end_to_end" in text
    assert "p95 n/a" in text


async def test_blocked_loop_shows_lag():
    sampler = LoopLagSampler()
    sampler.start()
    await asyncio.sleep(0.05)
    time.sleep(0.2)
    await asyncio.sleep(0.05)
    await sampler.stop()
    assert sampler.max_ms >= 190
    assert sampler.p95_ms >= 0


async def test_stop_leaves_no_task_pending():
    before = asyncio.all_tasks()
    sampler = LoopLagSampler()
    sampler.start()
    await asyncio.sleep(0.03)
    await sampler.stop()
    assert asyncio.all_tasks() == before


async def test_idle_loop_has_small_lag_and_stop_is_idempotent():
    sampler = LoopLagSampler()
    assert sampler.max_ms == 0.0
    assert sampler.p95_ms == 0.0
    sampler.start()
    await asyncio.sleep(0.05)
    await sampler.stop()
    await sampler.stop()
    assert sampler.max_ms < 100


def test_lag_p95_is_the_ninety_fifth_percentile_of_the_samples():
    sampler = LoopLagSampler()
    sampler._lags_ms = [float(value) for value in range(1, 21)]
    assert sampler.p95_ms == pytest.approx(19.05)
    assert sampler.max_ms == 20.0
