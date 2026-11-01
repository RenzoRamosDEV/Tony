"""Voice engine ports. PCM travels as raw little-endian float32 mono bytes, so the core
needs no numpy: 16 kHz from the microphone, the engine's rate (24 kHz) to the speakers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

INPUT_RATE = 16_000
OUTPUT_RATE = 24_000
FLOAT32_BYTES = 4
WINDOW_SAMPLES = 512
WINDOW_BYTES = WINDOW_SAMPLES * FLOAT32_BYTES
WINDOW_MS = WINDOW_SAMPLES * 1000 // INPUT_RATE


@dataclass(frozen=True)
class Clip:
    pcm: bytes
    rate: int = OUTPUT_RATE


class AudioInput(Protocol):
    def open(self, on_frame: Callable[[bytes], None]) -> None: ...

    def close(self) -> None: ...


class AudioOutput(Protocol):
    def play(self, clip: Clip) -> None:
        """Play the clip, returning once it has finished or `stop()` interrupted it."""

    def stop(self) -> None: ...


class Vad(Protocol):
    def is_speech(self, window: bytes) -> bool: ...

    def reset(self) -> None: ...


class Stt(Protocol):
    def transcribe(self, pcm: bytes) -> str: ...


class Tts(Protocol):
    def synthesize(self, text: str, voice: str) -> Clip:
        """Synthesise `text` with a `voice.tts` value such as `kokoro/ef_dora,bf_emma`."""
