from array import array

import pytest

from tony.core.voice.levels import LevelMeter, envelope, level
from tony.core.voice.ports import OUTPUT_RATE, Clip


def pcm(value: float, samples: int) -> bytes:
    return array("f", [value] * samples).tobytes()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 0.0), (0.05, 0.25), (0.2, 1.0), (0.5, 1.0), (-0.05, 0.25), (0.0333, 0.17)],
    ids=["silence", "rms-0.05", "full-scale", "clamped", "negative", "rounded"],
)
def test_level_is_rms_over_full_scale_clamped_and_rounded(value, expected):
    assert level(pcm(value, 512)) == expected


def test_level_of_empty_pcm_is_zero():
    assert level(b"") == 0.0


def test_level_mixes_samples_by_rms():
    assert level(array("f", [0.1, -0.1, 0.0, 0.0]).tobytes()) == 0.35


@pytest.mark.parametrize(
    ("samples", "frames"),
    [(OUTPUT_RATE, 20), (OUTPUT_RATE + OUTPUT_RATE // 100, 21), (0, 0), (1, 1)],
    ids=["1s", "1.01s", "empty", "one-sample"],
)
def test_envelope_has_one_value_per_50_ms_frame(samples, frames):
    assert len(envelope(Clip(pcm(0.05, samples)))) == frames


def test_envelope_values_are_the_level_of_each_frame():
    clip = Clip(pcm(0.05, 1200) + pcm(0.0, 1200) + pcm(0.2, 1200))
    assert envelope(clip) == [0.25, 0.0, 1.0]


def test_envelope_follows_the_clip_rate():
    assert len(envelope(Clip(pcm(0.1, 16_000), rate=16_000))) == 20


def test_meter_with_nothing_set_samples_none():
    assert LevelMeter().sample(0.0) is None


def test_meter_samples_the_latest_input_level():
    meter = LevelMeter()
    meter.set_input(0.3)
    meter.set_input(0.6)
    assert meter.sample(5.0) == ("input", 0.6)


def test_cleared_input_samples_none():
    meter = LevelMeter()
    meter.set_input(0.3)
    meter.clear_input()
    assert meter.sample(5.0) is None


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (0.0, ("output", 0.1)),
        (0.049, ("output", 0.1)),
        (0.05, ("output", 0.2)),
        (0.149, ("output", 0.3)),
        (0.15, None),
        (9.0, None),
        (-0.01, None),
    ],
)
def test_output_samples_the_envelope_value_for_the_elapsed_time(elapsed, expected):
    meter = LevelMeter()
    meter.start_output([0.1, 0.2, 0.3], 100.0)
    assert meter.sample(100.0 + elapsed) == expected


def test_output_wins_over_input():
    meter = LevelMeter()
    meter.set_input(0.9)
    meter.start_output([0.1], 0.0)
    assert meter.sample(0.0) == ("output", 0.1)


def test_input_is_sampled_again_after_the_output_ends():
    meter = LevelMeter()
    meter.set_input(0.9)
    meter.start_output([0.1], 0.0)
    assert meter.sample(0.05) == ("input", 0.9)


def test_stopped_output_samples_none():
    meter = LevelMeter()
    meter.start_output([0.1, 0.2], 0.0)
    meter.stop_output()
    assert meter.sample(0.0) is None
