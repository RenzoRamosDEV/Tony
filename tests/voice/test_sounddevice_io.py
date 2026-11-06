import sys

from tony.core.voice.engines.sounddevice_io import SoundDeviceInput, _resolve_device


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


DEVICES = [{"name": "Mic A"}, {"name": "Mic B"}]


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
