import threading
import time
from collections.abc import Callable

from tony.core.voice.levels import LevelMeter, envelope
from tony.core.voice.ports import AudioOutput, Clip, Tts
from tony.core.voice.stages import Report, StageThread
from tony.core.voice.timing import NullTimings, StageTimings


class Speaker:
    """Synthesises and plays sentences in order on the `tony-tts` and `tony-playback` threads.
    `stop_speaking` bumps a generation counter so sentences queued before it are discarded."""

    def __init__(
        self,
        tts: Tts,
        output: AudioOutput,
        report: Report,
        *,
        meter: LevelMeter | None = None,
        clock: Callable[[], float] = time.monotonic,
        timings: StageTimings | NullTimings | None = None,
    ) -> None:
        self._tts = tts
        self._output = output
        self._meter = meter or LevelMeter()
        self._clock = clock
        self._timings = timings or NullTimings()
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = 0
        self._idle = threading.Event()
        self._idle.set()
        self._drained_callbacks: list[Callable[[], None]] = []
        self._synthesis = StageThread("tts", self._synthesize, report)
        self._playback = StageThread("playback", self._play, report)

    def start(self) -> None:
        self._synthesis.start()
        self._playback.start()

    def say(self, text: str, voice: str, *, turn: int | None = None) -> None:
        with self._lock:
            self._pending += 1
            self._idle.clear()
            self._synthesis.put((self._generation, text, voice, turn))

    def stop_speaking(self) -> None:
        with self._lock:
            self._generation += 1
            dropped = self._synthesis.clear() + self._playback.clear()
        self._meter.stop_output()
        self._output.stop()
        self._finished(dropped)

    def wait_drained(self, timeout: float) -> bool:
        return self._idle.wait(timeout)

    def on_drained(self, callback: Callable[[], None]) -> None:
        """Call `callback` once every queued sentence has been played or dropped."""
        with self._lock:
            if self._pending:
                self._drained_callbacks.append(callback)
                return
        callback()

    def close(self) -> None:
        self.stop_speaking()
        self._synthesis.stop()
        self._playback.stop()

    def set_device(self, device: str | None) -> bool:
        return self._output.set_device(device)

    def _synthesize(self, item: tuple[int, str, str, int | None]) -> None:
        generation, text, voice, turn = item
        if generation != self._generation:
            self._finished(1)
            return
        try:
            self._timings.mark(turn, "synthesis_start")
            clip = self._tts.synthesize(text, voice)
            self._timings.mark(turn, "synthesis_end")
        except Exception:
            self._finished(1)
            raise
        self._playback.put((generation, clip, turn))

    def _play(self, item: tuple[int, Clip, int | None]) -> None:
        generation, clip, turn = item
        try:
            if generation == self._generation:
                self._timings.mark(turn, "playback_start")
                self._play_metered(clip)
        finally:
            self._finished(1)

    def _play_metered(self, clip: Clip) -> None:
        self._meter.start_output(envelope(clip), self._clock())
        try:
            self._output.play(clip)
        finally:
            self._meter.stop_output()

    def _finished(self, count: int) -> None:
        with self._lock:
            self._pending -= count
            if self._pending:
                return
            self._idle.set()
            callbacks, self._drained_callbacks = self._drained_callbacks, []
        for callback in callbacks:
            callback()
