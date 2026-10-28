"""Voice doubles over the core ports: energy VAD, fixed-text STT, sine TTS, recording sink."""

from __future__ import annotations

import math
from array import array
from collections.abc import Iterator
from typing import Any

from tony.core.voice.ports import OUTPUT_SAMPLE_RATE, AudioChunk, Transcript, Utterance

SPEECH_RMS = 0.01
CHUNK_MS = 150
CHUNKS_PER_SENTENCE = 2
SINE_HZ = 440.0


class FakeVad:
    """Speech is any window whose RMS energy exceeds SPEECH_RMS."""

    def __init__(self) -> None:
        self.resets = 0

    def classify(self, window: bytes) -> bool:
        samples = array("f")
        samples.frombytes(window)
        if not samples:
            return False
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        return rms > SPEECH_RMS

    def reset(self) -> None:
        self.resets += 1


class FakeStt:
    def __init__(self, text: str, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[tuple[Utterance, str]] = []

    def transcribe(self, utterance: Utterance, language: str) -> Transcript:
        self.calls.append((utterance, language))
        if self.fail:
            raise RuntimeError("el transcriptor falló")
        return Transcript(self.text, language, utterance.duration_ms)


def sine_chunk(duration_ms: int = CHUNK_MS) -> AudioChunk:
    count = OUTPUT_SAMPLE_RATE * duration_ms // 1_000
    pcm = array(
        "h",
        (
            int(0.3 * 32767 * math.sin(2 * math.pi * SINE_HZ * i / OUTPUT_SAMPLE_RATE))
            for i in range(count)
        ),
    )
    return AudioChunk(pcm16=pcm.tobytes(), sample_rate=OUTPUT_SAMPLE_RATE)


class FakeTts:
    """300 ms of a 440 Hz sine per sentence, in two chunks; can fail at a given sentence."""

    def __init__(self, fail_at_sentence: int | None = None) -> None:
        self.fail_at_sentence = fail_at_sentence
        self.sentences: list[str] = []
        self.voices: list[str] = []
        self.running = 0
        self.peak_running = 0

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        self.sentences.append(text)
        self.voices.append(voice)
        if self.fail_at_sentence is not None and len(self.sentences) == self.fail_at_sentence:
            raise RuntimeError(f"la síntesis falló en la frase {self.fail_at_sentence}")
        return self._chunks()

    def _chunks(self) -> Iterator[AudioChunk]:
        self.running += 1
        self.peak_running = max(self.peak_running, self.running)
        try:
            for _ in range(CHUNKS_PER_SENTENCE):
                yield sine_chunk()
        finally:
            self.running -= 1


class ListSpeechSink:
    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    async def start(self) -> None:
        self.events.append(("start",))

    async def chunk(self, seq: int, sentence_index: int, audio: AudioChunk) -> None:
        self.events.append(("chunk", seq, sentence_index, audio))

    async def end(self) -> None:
        self.events.append(("end",))

    async def cancelled(self) -> None:
        self.events.append(("cancelled",))

    async def failed(self, error: str) -> None:
        self.events.append(("failed", error))

    def types(self) -> list[str]:
        return [event[0] for event in self.events]

    @property
    def chunks(self) -> list[tuple[int, int, AudioChunk]]:
        return [(e[1], e[2], e[3]) for e in self.events if e[0] == "chunk"]

    @property
    def failures(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "failed"]
