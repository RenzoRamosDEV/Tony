"""The committed WAV fixtures are short, PCM 16 kHz mono Int16 and reproducible."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from tests.fixtures.audio.generate import (
    CHANNELS,
    FIXTURES,
    FIXTURES_DIR,
    MAX_DURATION_MS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    generate,
    read_wav_float32,
)

EXPECTED_DURATIONS_MS = {
    "speech_1500ms.wav": 2_300,
    "short_200ms.wav": 1_200,
    "noise_3s.wav": 3_000,
    "tone_3s.wav": 3_000,
    "silence_1s.wav": 1_000,
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_is_short_pcm_16k_mono_int16(name: str) -> None:
    with wave.open(str(FIXTURES_DIR / name), "rb") as handle:
        params = handle.getparams()

    assert (params.nchannels, params.sampwidth, params.framerate) == (
        CHANNELS,
        SAMPLE_WIDTH,
        SAMPLE_RATE,
    )
    duration_ms = params.nframes * 1_000 // SAMPLE_RATE
    assert duration_ms == EXPECTED_DURATIONS_MS[name]
    assert duration_ms <= MAX_DURATION_MS
    assert (FIXTURES_DIR / name).stat().st_size < 100_000


def test_regenerating_produces_identical_bytes(tmp_path: Path) -> None:
    regenerated = generate(tmp_path)

    assert set(regenerated) == set(EXPECTED_DURATIONS_MS)
    for name, data in regenerated.items():
        assert data == (FIXTURES_DIR / name).read_bytes(), name


def test_float32_view_has_one_sample_per_frame_in_range() -> None:
    pcm = read_wav_float32(FIXTURES_DIR / "silence_1s.wav")
    loud = read_wav_float32(FIXTURES_DIR / "tone_3s.wav")

    assert len(pcm) == SAMPLE_RATE * 4
    assert set(pcm) == {0}
    assert len(loud) == 3 * SAMPLE_RATE * 4
