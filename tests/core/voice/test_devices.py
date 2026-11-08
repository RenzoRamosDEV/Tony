from tony.core.voice.engines.devices import list_devices

SINK = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {"media.class": "Audio/Sink", "node.name": "alsa_output.speaker", "node.description": "Built-in Speaker"}},
}
SOURCE = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {"media.class": "Audio/Source", "node.name": "alsa_input.mic", "node.description": "Built-in Mic"}},
}
HEADSET_SINK = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {"media.class": "Audio/Sink", "node.name": "bluez_output.headset", "node.description": "USB Headset"}},
}
HEADSET_SOURCE = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {"media.class": "Audio/Source", "node.name": "bluez_input.headset", "node.description": "USB Headset"}},
}
STREAM = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {"media.class": "Stream/Output/Audio", "node.name": "chrome", "node.description": "Google Chrome"}},
}
DEFAULTS = {
    "type": "PipeWire:Interface:Metadata",
    "props": {"metadata.name": "default"},
    "metadata": [
        {"key": "default.audio.sink", "value": {"name": "alsa_output.speaker"}},
        {"key": "default.audio.source", "value": {"name": "bluez_input.headset"}},
    ],
}
NODES = [SINK, SOURCE, HEADSET_SINK, HEADSET_SOURCE, STREAM, DEFAULTS]


def test_list_devices_splits_by_channel_kind():
    devices = list_devices(query=lambda: NODES)
    names = {(d.name, d.kind) for d in devices}
    assert names == {
        ("Built-in Speaker", "output"), ("Built-in Mic", "input"),
        ("USB Headset", "output"), ("USB Headset", "input"),
    }


def test_list_devices_marks_the_default_per_kind():
    devices = list_devices(query=lambda: NODES)
    assert next(d for d in devices if d.name == "Built-in Speaker").is_default
    assert next(d for d in devices if d.name == "USB Headset" and d.kind == "input").is_default
    assert not next(d for d in devices if d.name == "USB Headset" and d.kind == "output").is_default
    assert not next(d for d in devices if d.name == "Built-in Mic").is_default


def test_list_devices_excludes_non_device_stream_nodes():
    devices = list_devices(query=lambda: NODES)
    assert all(d.name != "Google Chrome" for d in devices)


def test_list_devices_returns_empty_when_the_query_fails():
    def failing_query():
        raise OSError("pw-dump not found")

    assert list_devices(query=failing_query) == ()
