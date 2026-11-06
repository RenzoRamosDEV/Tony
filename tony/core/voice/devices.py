from dataclasses import dataclass
from typing import Any, Callable, Literal


def _default_query() -> tuple[Any, Any]:
    import sounddevice

    return sounddevice.query_devices(), sounddevice.default.device


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    kind: Literal["input", "output"]
    is_default: bool


def list_devices(*, query: Callable[[], Any] = _default_query) -> tuple[DeviceInfo, ...]:
    raw_devices, default_pair = query()
    default_input, default_output = default_pair
    devices: list[DeviceInfo] = []
    for index, device in enumerate(raw_devices):
        if device["max_input_channels"] > 0:
            devices.append(DeviceInfo(name=device["name"], kind="input", is_default=index == default_input))
        if device["max_output_channels"] > 0:
            devices.append(DeviceInfo(name=device["name"], kind="output", is_default=index == default_output))
    return tuple(devices)
