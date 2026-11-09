from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from tony.core.voice.ports import INPUT_RATE, WINDOW_SAMPLES, Clip


@dataclass(frozen=True)
class DeviceChoice:
    """`index` None is the system default; `matched` is False when a named device is missing."""

    index: int | None
    matched: bool


def resolve_device(name: str | None, kind: Literal["input", "output"]) -> DeviceChoice:
    if name is None:
        return DeviceChoice(index=None, matched=True)
    import sounddevice

    channels = f"max_{kind}_channels"
    candidates = [
        (index, device["name"])
        for index, device in enumerate(sounddevice.query_devices())
        if device.get(channels, 0) > 0
    ]
    for normalize in (str, _normalized):
        for index, found in candidates:
            if normalize(found) == normalize(name):
                return DeviceChoice(index=index, matched=True)
    return DeviceChoice(index=None, matched=False)


def _resolve_device(name: str | None, kind: Literal["input", "output"]) -> int | None:
    return resolve_device(name, kind).index


def _normalized(name: str) -> str:
    return name.strip().casefold()


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

    def set_device(self, device: str | None) -> bool:
        self._device = device
        if self._stream is not None and self._on_frame is not None:
            on_frame = self._on_frame
            self.close()
            self.open(on_frame)
        return resolve_device(device, "input").matched


class SoundDeviceOutput:
    """Plays clips on the configured (or default) output; `stop` interrupts the current clip."""

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

    def set_device(self, device: str | None) -> bool:
        self._device = device
        return resolve_device(device, "output").matched
