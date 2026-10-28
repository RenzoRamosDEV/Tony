"""Whether Tony's voice is (estimated to be) playing on the client.

Opened by `tts.start`; each `tts.chunk` extends the estimated end by its duration, counted
from the first chunk. It closes with the client's `playback.stopped`, with `tts.cancelled`,
or on its own two seconds after the estimated end, for clients that never report.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

GRACE_S = 2.0


@dataclass
class _Playing:
    first_chunk_at: float | None = None
    audio_s: float = 0.0

    def deadline(self) -> float | None:
        if self.first_chunk_at is None:
            return None
        return self.first_chunk_at + self.audio_s + GRACE_S


class PlaybackWindow:
    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        self._playing: dict[str, _Playing] = {}

    def started(self, message_id: str) -> None:
        self._playing[message_id] = _Playing()

    def chunk(self, message_id: str, duration_ms: int) -> None:
        playing = self._playing.get(message_id)
        if playing is None:
            return
        if playing.first_chunk_at is None:
            playing.first_chunk_at = self._monotonic()
        playing.audio_s += duration_ms / 1_000

    def ended(self, message_id: str) -> None:
        """Synthesis finished: a reply that produced no audio is not playing at all."""
        playing = self._playing.get(message_id)
        if playing is not None and playing.first_chunk_at is None:
            del self._playing[message_id]

    def stopped(self, message_id: str) -> None:
        self._playing.pop(message_id, None)

    cancelled = stopped

    def playing(self) -> list[str]:
        """Messages still playing, oldest first; expired ones are forgotten."""
        now = self._monotonic()
        for message_id, playing in list(self._playing.items()):
            deadline = playing.deadline()
            if deadline is not None and now >= deadline:
                del self._playing[message_id]
        return list(self._playing)

    def speaking(self) -> bool:
        return bool(self.playing())
