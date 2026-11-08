from dataclasses import dataclass
from typing import Any, Callable, Literal

_SINK = "Audio/Sink"
_SOURCE = "Audio/Source"
_NODE = "PipeWire:Interface:Node"
_METADATA = "PipeWire:Interface:Metadata"
_DUMP_TIMEOUT_S = 5


def _default_query() -> list[dict[str, Any]]:
    import json
    import subprocess

    output = subprocess.run(
        ["pw-dump"], capture_output=True, text=True, timeout=_DUMP_TIMEOUT_S, check=True
    ).stdout
    return json.loads(output)


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    kind: Literal["input", "output"]
    is_default: bool


def list_devices(*, query: Callable[[], list[dict[str, Any]]] = _default_query) -> tuple[DeviceInfo, ...]:
    """The real sinks/sources PipeWire routes audio to, matching what the desktop's own sound
    settings show: no ALSA duplicates, app streams or internal helper nodes."""
    try:
        nodes = query()
    except Exception:
        return ()
    default_sink, default_source = _defaults(nodes)
    devices: list[DeviceInfo] = []
    for node in nodes:
        if node.get("type") != _NODE:
            continue
        props = ((node.get("info") or {}).get("props")) or {}
        media_class = props.get("media.class")
        name = props.get("node.description") or props.get("node.nick") or props.get("node.name")
        node_name = props.get("node.name")
        if name is None or media_class not in (_SINK, _SOURCE):
            continue
        if media_class == _SINK:
            devices.append(DeviceInfo(name=name, kind="output", is_default=node_name == default_sink))
        else:
            devices.append(DeviceInfo(name=name, kind="input", is_default=node_name == default_source))
    return tuple(devices)


def _defaults(nodes: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    sink = source = None
    for node in nodes:
        if node.get("type") != _METADATA or (node.get("props") or {}).get("metadata.name") != "default":
            continue
        for entry in node.get("metadata") or []:
            value = entry.get("value")
            if not isinstance(value, dict):
                continue
            if entry.get("key") == "default.audio.sink":
                sink = value.get("name")
            elif entry.get("key") == "default.audio.source":
                source = value.get("name")
    return sink, source
