"""Offline voice engine doubles: scripted microphone, threshold VAD, scripted STT, a TTS that
encodes the text in the clip and an output that records what it played."""

import struct
import threading
import time
from collections.abc import Callable, Iterable

from tony.core.voice.levels import LevelMeter
from tony.core.voice.ports import FLOAT32_BYTES, OUTPUT_RATE, WINDOW_SAMPLES, Clip

SPEECH_LEVEL = 0.9


def window(speech: bool) -> bytes:
    return struct.pack(f"<{WINDOW_SAMPLES}f", *([SPEECH_LEVEL if speech else 0.0] * WINDOW_SAMPLES))


def frames(pattern: str) -> list[bytes]:
    """One 32 ms window per character: `S` speech, anything else silence."""
    return [window(mark == "S") for mark in pattern]


class ScriptedAudioInput:
    """Delivers its frames synchronously on `open`; optionally fails to open. With `sessions`,
    each open delivers the next list of frames (none once they run out)."""

    def __init__(
        self,
        frames: Iterable[bytes] = (),
        *,
        error: Exception | None = None,
        sessions: Iterable[Iterable[bytes]] | None = None,
    ) -> None:
        self._frames = list(frames)
        self._error = error
        self._sessions = None if sessions is None else [list(s) for s in sessions]
        self.opened = 0
        self.closed = 0
        self.device: str | None = None
        self.unavailable_devices: set[str] = set()

    def open(self, on_frame: Callable[[bytes], None]) -> None:
        self.opened += 1
        if self._error is not None:
            raise self._error
        if self._sessions is not None:
            self._frames = self._sessions.pop(0) if self._sessions else []
        for frame in self._frames:
            on_frame(frame)

    def close(self) -> None:
        self.closed += 1

    def set_device(self, device: str | None) -> bool:
        self.device = device
        return device not in self.unavailable_devices


class ThresholdVad:
    """Speech when the first float32 sample of the window is above 0.5."""

    def __init__(self) -> None:
        self.resets = 0

    def is_speech(self, window: bytes) -> bool:
        return struct.unpack_from("<f", window)[0] > 0.5

    def reset(self) -> None:
        self.resets += 1


class ScriptedStt:
    """Returns (or raises) its scripted results in order; unscripted calls return ``."""

    def __init__(self, *results: str | Exception) -> None:
        self._results = list(results)
        self.pcms: list[bytes] = []

    def transcribe(self, pcm: bytes) -> str:
        self.pcms.append(pcm)
        result = self._results.pop(0) if self._results else ""
        if isinstance(result, Exception):
            raise result
        return result


class TextTts:
    """The clip's PCM is the UTF-8 text; texts in `fail_on` raise."""

    def __init__(self, fail_on: Iterable[str] = ()) -> None:
        self._fail_on = set(fail_on)
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, voice: str) -> Clip:
        self.calls.append((text, voice))
        if text in self._fail_on:
            raise RuntimeError(f"cannot synthesise {text}")
        return Clip(text.encode("utf-8"))


class RecordingAudioOutput:
    """Records played texts; with `blocking`, each play waits for `release()` or `stop()`."""

    def __init__(self, *, blocking: bool = False, fail_on: Iterable[str] = ()) -> None:
        self._blocking = blocking
        self._fail_on = set(fail_on)
        self._released = threading.Event()
        self.started = threading.Event()
        self.played: list[str] = []
        self.rates: list[int] = []
        self.stops = 0
        self.device: str | None = None
        self.unavailable_devices: set[str] = set()

    def set_device(self, device: str | None) -> bool:
        self.device = device
        return device not in self.unavailable_devices

    def play(self, clip: Clip) -> None:
        text = clip.pcm.decode("utf-8")
        if text in self._fail_on:
            raise RuntimeError(f"cannot play {text}")
        self.played.append(text)
        self.rates.append(clip.rate)
        self.started.set()
        if self._blocking:
            self._released.wait(5)
            self._released.clear()

    def release(self) -> None:
        self._released.set()

    def stop(self) -> None:
        self.stops += 1
        self._released.set()


class RecordingMeter(LevelMeter):
    """A real meter that also logs each hook call into `log` (shared with other doubles)."""

    def __init__(self, log: list | None = None) -> None:
        super().__init__()
        self.log = [] if log is None else log

    def set_input(self, value: float) -> None:
        self.log.append(("input", value))
        super().set_input(value)

    def clear_input(self) -> None:
        self.log.append(("clear_input",))
        super().clear_input()

    def start_output(self, values: list[float], now: float) -> None:
        self.log.append(("start_output", len(values)))
        super().start_output(values, now)

    def stop_output(self) -> None:
        self.log.append(("stop_output",))
        super().stop_output()


class ToneTts:
    """Every sentence becomes a constant tone of `seconds` at `amplitude`."""

    def __init__(self, seconds: float = 1.0, amplitude: float = 0.05) -> None:
        samples = int(OUTPUT_RATE * seconds)
        self._pcm = struct.pack(f"<{samples}f", *([amplitude] * samples))

    def synthesize(self, text: str, voice: str) -> Clip:
        return Clip(self._pcm)


class RealtimeAudioOutput:
    """Plays each clip for its real duration unless `stop()` interrupts it."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self.started = threading.Event()
        self.finished = threading.Event()
        self.finished_at: float | None = None
        self.device: str | None = None
        self.unavailable_devices: set[str] = set()

    def play(self, clip: Clip) -> None:
        self._stop.clear()
        self.started.set()
        self._stop.wait(len(clip.pcm) / FLOAT32_BYTES / clip.rate)
        self.finished_at = time.monotonic()
        self.finished.set()

    def stop(self) -> None:
        self._stop.set()

    def set_device(self, device: str | None) -> bool:
        self.device = device
        return device not in self.unavailable_devices
