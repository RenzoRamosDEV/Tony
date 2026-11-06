from collections.abc import Callable
from typing import Any, Literal

from tony.core.voice.ports import INPUT_RATE, WINDOW_SAMPLES, Clip


def _resolve_device(name: str | None, kind: Literal["input", "output"]) -> int | None:
    if name is None:
        return None
    import sounddevice

    for index, device in enumerate(sounddevice.query_devices()):
        if device["name"] == name:
            return index
    return None


class SoundDeviceInput:
    """The configured (or default) microphone as 16 kHz mono float32 blocks of one VAD window."""

    def __init__(self, device: str | None = None) -> None:
        self._device = device
        self._stream: Any = None
        self._on_frame: Callable[[bytes], None] | None = None

    def open(self, on_frame: Callable[[bytes], None]) -> None:
        import sounddevice

        self._on_frame = on_frame

        def callback(data: Any, frames: int, time: Any, status: Any) -> None:
            on_frame(bytes(data))

        stream = sounddevice.RawInputStream(
            samplerate=INPUT_RATE,
            channels=1,
            dtype="float32",
            blocksize=WINDOW_SAMPLES,
            device=_resolve_device(self._device, "input"),
            callback=callback,
        )
        stream.start()
        self._stream = stream

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    def set_device(self, device: str | None) -> None:
        self._device = device
        if self._stream is not None and self._on_frame is not None:
            on_frame = self._on_frame
            self.close()
            self.open(on_frame)


class SoundDeviceOutput:
    """Plays clips on the configured (or default) output; `stop` interrupts the clip being played."""

    def __init__(self, device: str | None = None) -> None:
        self._device = device

    def play(self, clip: Clip) -> None:
        import numpy
        import sounddevice

        sounddevice.play(
            numpy.frombuffer(clip.pcm, dtype=numpy.float32),
            clip.rate,
            device=_resolve_device(self._device, "output"),
        )
        sounddevice.wait()

    def stop(self) -> None:
        import sounddevice

        sounddevice.stop()

    def set_device(self, device: str | None) -> None:
        self._device = device
