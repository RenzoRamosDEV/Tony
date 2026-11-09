import sys

from tony.core.voice.engines.sounddevice_io import (
    DeviceChoice,
    SoundDeviceInput,
    SoundDeviceOutput,
    _resolve_device,
    resolve_device,
)


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        pass


class FakeSoundDevice:
    def __init__(self, devices):
        self._devices = devices
        self.streams = []

    def query_devices(self):
        return self._devices

    def RawInputStream(self, **kwargs):
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream


def mic(name):
    return {"name": name, "max_input_channels": 1, "max_output_channels": 0}


def speaker(name):
    return {"name": name, "max_input_channels": 0, "max_output_channels": 2}


DEVICES = [mic("Mic A"), mic("Mic B")]


def test_resolve_device_finds_index_by_name(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert _resolve_device("Mic B", "input") == 1


def test_resolve_device_falls_back_to_default_when_missing(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert _resolve_device("Mic Z", "input") is None


def test_set_device_reopens_an_open_stream_on_the_new_device(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    audio = SoundDeviceInput("Mic A")
    audio.open(lambda frame: None)
    audio.set_device("Mic B")
    assert fake.streams[0].stopped
    assert fake.streams[-1].kwargs["device"] == 1


def test_set_device_is_a_no_op_on_stream_state_when_nothing_is_open(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    audio = SoundDeviceInput("Mic A")
    audio.set_device("Mic B")
    assert fake.streams == []


def use(monkeypatch, devices):
    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice(devices))


def test_default_selection_matches_without_looking_at_devices(monkeypatch):
    use(monkeypatch, [])
    assert resolve_device(None, "input") == DeviceChoice(index=None, matched=True)


def test_exact_name_matches(monkeypatch):
    use(monkeypatch, DEVICES)
    assert resolve_device("Mic B", "input") == DeviceChoice(index=1, matched=True)


def test_name_ignoring_case_and_surrounding_spaces_matches(monkeypatch):
    use(monkeypatch, [mic("USB Mic")])
    assert resolve_device("  usb mic ", "input") == DeviceChoice(index=0, matched=True)


def test_exact_name_wins_over_a_normalized_one(monkeypatch):
    use(monkeypatch, [mic("usb mic"), mic("USB Mic")])
    assert resolve_device("USB Mic", "input").index == 1


def test_missing_name_uses_default_and_is_not_matched(monkeypatch):
    use(monkeypatch, DEVICES)
    assert resolve_device("Mic Z", "input") == DeviceChoice(index=None, matched=False)


def test_input_only_device_does_not_match_as_output(monkeypatch):
    use(monkeypatch, DEVICES)
    assert resolve_device("Mic A", "output") == DeviceChoice(index=None, matched=False)


def test_output_only_device_does_not_match_as_input(monkeypatch):
    use(monkeypatch, [speaker("Speakers")])
    assert resolve_device("Speakers", "input") == DeviceChoice(index=None, matched=False)
    assert resolve_device("Speakers", "output") == DeviceChoice(index=0, matched=True)


def test_duplex_device_matches_both_kinds(monkeypatch):
    duplex = {"name": "Headset", "max_input_channels": 1, "max_output_channels": 2}
    use(monkeypatch, [duplex])
    assert resolve_device("Headset", "input").matched
    assert resolve_device("Headset", "output").matched


def test_input_set_device_reports_whether_it_matched(monkeypatch):
    use(monkeypatch, DEVICES)
    audio = SoundDeviceInput()
    assert audio.set_device("Mic B") is True
    assert audio.set_device("Mic Z") is False
    assert audio.set_device(None) is True


def test_output_set_device_reports_whether_it_matched(monkeypatch):
    use(monkeypatch, [speaker("Speakers")])
    output = SoundDeviceOutput()
    assert output.set_device("speakers") is True
    assert output.set_device("Nope") is False
    assert output.set_device(None) is True
