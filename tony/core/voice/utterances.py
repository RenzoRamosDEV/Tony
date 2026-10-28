"""Turns a stream of classified VAD windows into complete utterances (pure, integer ms)."""

from __future__ import annotations

from tony.core.voice.ports import (
    FLOAT32_BYTES,
    SPEECH_THRESHOLD,
    VAD_WINDOW_SAMPLES,
    Utterance,
    Vad,
)

WINDOW_MS = 32
END_SILENCE_MS = 500
MIN_SPEECH_MS = 300
MAX_UTTERANCE_MS = 30_000
WINDOW_BYTES = VAD_WINDOW_SAMPLES * FLOAT32_BYTES


class UtteranceAssembler:
    """Closes an utterance after `end_silence_ms` of silence, drops ones with less than
    `min_speech_ms` of speech and force-cuts at `max_utterance_ms` of total duration;
    trailing silence is trimmed."""

    def __init__(
        self,
        window_ms: int = WINDOW_MS,
        end_silence_ms: int = END_SILENCE_MS,
        min_speech_ms: int = MIN_SPEECH_MS,
        max_utterance_ms: int = MAX_UTTERANCE_MS,
    ) -> None:
        self._window_ms = window_ms
        self._end_silence_ms = end_silence_ms
        self._min_speech_ms = min_speech_ms
        self._max_utterance_ms = max_utterance_ms
        self._windows: list[bytes] = []
        self._speech_windows = 0
        self._last_speech_index = -1
        self._trailing_silence_ms = 0

    @property
    def pending_ms(self) -> int:
        return len(self._windows) * self._window_ms

    @property
    def speech_ms(self) -> int:
        """Speech accumulated by the open utterance."""
        return self._speech_windows * self._window_ms

    def push(self, window: bytes, is_speech: bool) -> list[Utterance]:
        if not self._windows and not is_speech:
            return []
        self._windows.append(window)
        if is_speech:
            self._speech_windows += 1
            self._last_speech_index = len(self._windows) - 1
            self._trailing_silence_ms = 0
        else:
            self._trailing_silence_ms += self._window_ms
        if self.pending_ms >= self._max_utterance_ms:
            return self._close()
        if self._trailing_silence_ms >= self._end_silence_ms:
            return self._close()
        return []

    def flush(self) -> list[Utterance]:
        return self._close()

    def reset(self) -> None:
        self._windows = []
        self._speech_windows = 0
        self._last_speech_index = -1
        self._trailing_silence_ms = 0

    def _close(self) -> list[Utterance]:
        speech = self._windows[: self._last_speech_index + 1]
        speech_ms = self.speech_ms
        self.reset()
        if speech_ms < self._min_speech_ms:
            return []
        return [Utterance(pcm=b"".join(speech), duration_ms=len(speech) * self._window_ms)]


class VadSegmenter:
    """Feeds Float32 PCM to a Vad in fixed windows and assembles the utterances it finds."""

    def __init__(self, vad: Vad, assembler: UtteranceAssembler | None = None) -> None:
        self._vad = vad
        self._assembler = assembler or UtteranceAssembler()
        self._remainder = b""

    @property
    def speech_ms(self) -> int:
        return self._assembler.speech_ms

    def feed(self, pcm: bytes, threshold: float = SPEECH_THRESHOLD) -> list[Utterance]:
        data = self._remainder + pcm
        utterances: list[Utterance] = []
        offset = 0
        while offset + WINDOW_BYTES <= len(data):
            window = data[offset : offset + WINDOW_BYTES]
            offset += WINDOW_BYTES
            found = self._assembler.push(window, self._vad.classify(window, threshold))
            if found:
                self._vad.reset()
                utterances += found
        self._remainder = data[offset:]
        return utterances

    def flush(self) -> list[Utterance]:
        self._remainder = b""
        self._vad.reset()
        return self._assembler.flush()

    def reset(self) -> None:
        """Start a new capture: drop the partial utterance and the VAD's recurrent state."""
        self._remainder = b""
        self._assembler.reset()
        self._vad.reset()
