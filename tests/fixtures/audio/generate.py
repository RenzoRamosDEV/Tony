"""Deterministic synthetic WAV fixtures (PCM 16 kHz mono Int16, no human voice, <= 3 s).

Run `python -m tests.fixtures.audio.generate` to (re)write them next to this module.
"""

from __future__ import annotations

import io
import math
import random
import struct
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2
FIXTURES_DIR = Path(__file__).parent
MAX_DURATION_MS = 3_000


def samples(duration_ms: int) -> int:
    return SAMPLE_RATE * duration_ms // 1_000


def silence(duration_ms: int) -> list[float]:
    return [0.0] * samples(duration_ms)


def tone(duration_ms: int, frequency_hz: float = 220.0, amplitude: float = 0.5) -> list[float]:
    return [
        amplitude * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE)
        for i in range(samples(duration_ms))
    ]


def modulated_tone(duration_ms: int, frequency_hz: float = 220.0) -> list[float]:
    """A tone whose amplitude breathes at 4 Hz, so energy varies like speech does."""
    return [
        0.5
        * (0.75 + 0.25 * math.sin(2 * math.pi * 4 * i / SAMPLE_RATE))
        * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE)
        for i in range(samples(duration_ms))
    ]


def noise(duration_ms: int, seed: int = 7, amplitude: float = 0.3) -> list[float]:
    generator = random.Random(seed)
    return [amplitude * generator.uniform(-1.0, 1.0) for _ in range(samples(duration_ms))]


def to_wav_bytes(pcm: list[float]) -> bytes:
    frames = array("h", (int(max(-1.0, min(1.0, value)) * 32767) for value in pcm))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames.tobytes())
    return buffer.getvalue()


def read_wav_float32(path: Path) -> bytes:
    """The PCM of a fixture as Float32 little-endian bytes, the format the voice ports take."""
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    ints = struct.unpack(f"<{len(frames) // SAMPLE_WIDTH}h", frames)
    return array("f", (value / 32768.0 for value in ints)).tobytes()


FIXTURES: dict[str, list[float]] = {
    "speech_1500ms.wav": modulated_tone(1_500) + silence(800),
    "short_200ms.wav": tone(200) + silence(1_000),
    "noise_3s.wav": noise(3_000),
    "tone_3s.wav": tone(3_000),
    "silence_1s.wav": silence(1_000),
}


def generate(out_dir: Path = FIXTURES_DIR) -> dict[str, bytes]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, pcm in FIXTURES.items():
        data = to_wav_bytes(pcm)
        (out_dir / name).write_bytes(data)
        written[name] = data
    return written


if __name__ == "__main__":
    for name, data in generate().items():
        print(f"{name}: {len(data)} bytes")
