"""Voice ports: audio value objects and the contracts of the VAD, STT, TTS engines and sinks.

PCM travels as raw little-endian bytes so the core stays free of numpy: Float32 at 16 kHz
mono on the way in, Int16 at 24 kHz mono on the way out. Engines convert at their boundary.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
FLOAT32_BYTES = 4
INT16_BYTES = 2
VAD_WINDOW_SAMPLES = 512
SPEECH_THRESHOLD = 0.5


class VoiceConfigError(ValueError):
    """A voice alias of config/tony.yaml names an unknown engine, model or voice."""


@dataclass(frozen=True)
class Utterance:
    """One stretch of speech: Float32 LE PCM at 16 kHz mono."""

    pcm: bytes
    duration_ms: int

    @property
    def sample_count(self) -> int:
        return len(self.pcm) // FLOAT32_BYTES


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    duration_ms: int


@dataclass(frozen=True)
class AudioChunk:
    """Synthesized audio: Int16 LE PCM mono."""

    pcm16: bytes
    sample_rate: int = OUTPUT_SAMPLE_RATE

    @property
    def duration_ms(self) -> int:
        return len(self.pcm16) // INT16_BYTES * 1_000 // self.sample_rate


@runtime_checkable
class Vad(Protocol):
    def classify(self, window: bytes, threshold: float) -> bool:
        """Whether a window of VAD_WINDOW_SAMPLES Float32 samples has a speech probability
        of at least `threshold`."""

    def reset(self) -> None:
        """Forget the state carried between windows of one utterance."""


@runtime_checkable
class Stt(Protocol):
    def transcribe(self, utterance: Utterance, language: str) -> Transcript: ...


@runtime_checkable
class Tts(Protocol):
    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]: ...


@runtime_checkable
class SpeechSink(Protocol):
    async def start(self) -> None: ...

    async def chunk(self, seq: int, sentence_index: int, audio: AudioChunk) -> None: ...

    async def end(self) -> None: ...

    async def cancelled(self) -> None: ...

    async def failed(self, error: str) -> None: ...
