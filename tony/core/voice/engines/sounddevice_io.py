from collections.abc import Callable
from typing import Any

from tony.core.voice.ports import INPUT_RATE, WINDOW_SAMPLES, Clip


class SoundDeviceInput:
    """The default microphone as 16 kHz mono float32 blocks of one VAD window."""

    def __init__(self) -> None:
        self._stream: Any = None

    def open(self, on_frame: Callable[[bytes], None]) -> None:
        import sounddevice

        def callback(data: Any, frames: int, time: Any, status: Any) -> None:
            on_frame(bytes(data))

        stream = sounddevice.RawInputStream(
            samplerate=INPUT_RATE,
            channels=1,
            dtype="float32",
            blocksize=WINDOW_SAMPLES,
            callback=callback,
        )
        stream.start()
        self._stream = stream

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()


class SoundDeviceOutput:
    """Plays clips on the default output; `stop` interrupts the clip being played."""

    def play(self, clip: Clip) -> None:
        import numpy
        import sounddevice

        sounddevice.play(numpy.frombuffer(clip.pcm, dtype=numpy.float32), clip.rate)
        sounddevice.wait()

    def stop(self) -> None:
        import sounddevice

        sounddevice.stop()
