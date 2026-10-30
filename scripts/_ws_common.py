"""Shared helpers for the manual WebSocket scripts in this folder.

Not part of the `tony` package and not covered by the standard test suite: these are
one-off scripts run by hand against a real, already-running `tony web` server, using the
real voice engines. They synthesize the spoken input with Tony's own TTS instead of a
microphone, so the checks are reproducible without recording audio.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tony.core.config import load_settings
from tony.core.voice.aliases import parse_alias
from tony.core.voice.engines import EngineRegistry

WS_URL = "ws://127.0.0.1:{port}/ws/chat"
INPUT_SAMPLE_RATE = 16_000
FRAME_MS = 32
FRAME_SAMPLES = INPUT_SAMPLE_RATE * FRAME_MS // 1_000


def synthesize_utterance(text: str, config: Path = Path("config/tony.yaml")) -> bytes:
    """Speak `text` with Tony's configured TTS voice and return it as 16 kHz Float32 PCM,
    ready to stream as `audio.chunk` frames."""
    settings = load_settings(config)
    registry = EngineRegistry(settings.voice)
    alias = parse_alias(settings.voice.tts)
    tts = registry.get_tts(settings.voice.tts)
    pcm24: list[int] = []
    for chunk in tts.synthesize(text, alias.voices[0][0]):
        pcm24.extend(np.frombuffer(chunk.pcm16, dtype="<i2"))
    audio24 = np.asarray(pcm24, dtype=np.float32) / 32768.0
    return resample(audio24, from_rate=24_000, to_rate=INPUT_SAMPLE_RATE)


def resample(audio: np.ndarray, *, from_rate: int, to_rate: int) -> bytes:
    """Linear resample of a mono Float32 signal; good enough for a round-trip test, not
    for production (the browser capture path has its own stateful resampler)."""
    if from_rate == to_rate or audio.size == 0:
        return audio.astype(np.float32).tobytes()
    duration_s = audio.size / from_rate
    out_len = max(1, int(round(duration_s * to_rate)))
    src_t = np.arange(audio.size) / from_rate
    dst_t = np.arange(out_len) / to_rate
    return np.interp(dst_t, src_t, audio).astype(np.float32).tobytes()


def frames(pcm: bytes, frame_samples: int = FRAME_SAMPLES) -> list[bytes]:
    frame_bytes = frame_samples * 4  # float32
    return [pcm[i : i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]


def envelope(type_: str, payload: dict | None = None, conversation_id: str | None = None) -> str:
    return json.dumps(
        {"v": 1, "type": type_, "conversation_id": conversation_id, "payload": payload or {}}
    )


def silence_frame(frame_samples: int = FRAME_SAMPLES) -> bytes:
    return np.zeros(frame_samples, dtype=np.float32).tobytes()
