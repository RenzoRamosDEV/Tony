from tony.core.voice.engines.devices import list_devices

FAKE_DEVICES = [
    {"name": "Built-in Mic", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
    {"name": "HDMI Out", "max_input_channels": 0, "max_output_channels": 2},
]


def test_list_devices_splits_by_channel_kind():
    devices = list_devices(query=lambda: (FAKE_DEVICES, [0, 2]))
    names = {(d.name, d.kind) for d in devices}
    assert names == {
        ("Built-in Mic", "input"), ("USB Headset", "input"),
        ("USB Headset", "output"), ("HDMI Out", "output"),
    }


def test_list_devices_marks_the_default_per_kind():
    devices = list_devices(query=lambda: (FAKE_DEVICES, [0, 2]))
    assert next(d for d in devices if d.name == "Built-in Mic").is_default
    assert next(d for d in devices if d.name == "HDMI Out" and d.kind == "output").is_default
    assert not next(d for d in devices if d.name == "USB Headset" and d.kind == "input").is_default
