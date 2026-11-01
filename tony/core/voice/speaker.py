import threading
from collections.abc import Callable

from tony.core.voice.ports import AudioOutput, Clip, Tts
from tony.core.voice.stages import Report, StageThread


class Speaker:
    """Synthesises and plays sentences in order on the `tony-tts` and `tony-playback` threads.
    `stop_speaking` bumps a generation counter so sentences queued before it are discarded."""

    def __init__(self, tts: Tts, output: AudioOutput, report: Report) -> None:
        self._tts = tts
        self._output = output
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

    def say(self, text: str, voice: str) -> None:
        with self._lock:
            self._pending += 1
            self._idle.clear()
            self._synthesis.put((self._generation, text, voice))

    def stop_speaking(self) -> None:
        with self._lock:
            self._generation += 1
            dropped = self._synthesis.clear() + self._playback.clear()
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

    def _synthesize(self, item: tuple[int, str, str]) -> None:
        generation, text, voice = item
        if generation != self._generation:
            self._finished(1)
            return
        try:
            clip = self._tts.synthesize(text, voice)
        except Exception:
            self._finished(1)
            raise
        self._playback.put((generation, clip))

    def _play(self, item: tuple[int, Clip]) -> None:
        generation, clip = item
        try:
            if generation == self._generation:
                self._output.play(clip)
        finally:
            self._finished(1)

    def _finished(self, count: int) -> None:
        with self._lock:
            self._pending -= count
            if self._pending:
                return
            self._idle.set()
            callbacks, self._drained_callbacks = self._drained_callbacks, []
        for callback in callbacks:
            callback()
