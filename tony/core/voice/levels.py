"""Loudness levels of float32 PCM for the orb, as numbers only: audio never leaves the core."""

import math
import threading
from array import array

from tony.core.voice.ports import FLOAT32_BYTES, Clip

FULL_SCALE_RMS = 0.2
FRAME_MS = 50
FRAME_S = FRAME_MS / 1000
# Absorbs float error so that exactly 0.05 s after the start reads frame 1, not frame 0.
EPSILON_FRAMES = 1e-9

Sample = tuple[str, float]


def level(pcm: bytes) -> float:
    samples = array("f", pcm)
    if not samples:
        return 0.0
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    return round(min(1.0, rms / FULL_SCALE_RMS), 2)


def envelope(clip: Clip, frame_ms: int = FRAME_MS) -> list[float]:
    frame_bytes = clip.rate * frame_ms // 1000 * FLOAT32_BYTES
    return [level(clip.pcm[at : at + frame_bytes]) for at in range(0, len(clip.pcm), frame_bytes)]


class LevelMeter:
    """Latest microphone level and the playing clip's envelope, shared across voice threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._input: float | None = None
        self._output: list[float] = []
        self._output_start = 0.0

    def set_input(self, value: float) -> None:
        with self._lock:
            self._input = value

    def clear_input(self) -> None:
        with self._lock:
            self._input = None

    def start_output(self, values: list[float], now: float) -> None:
        with self._lock:
            self._output = values
            self._output_start = now

    def stop_output(self) -> None:
        with self._lock:
            self._output = []

    def sample(self, now: float) -> Sample | None:
        with self._lock:
            elapsed = now - self._output_start
            index = int(elapsed / FRAME_S + EPSILON_FRAMES)
            if self._output and elapsed >= 0 and index < len(self._output):
                return ("output", self._output[index])
            if self._input is not None:
                return ("input", self._input)
            return None
