import pytest

from tests.core.orchestrator.test_runtime import Harness, home_for
from tests.core.voice.service_harness import ALEX, EDITH, FakeLoader, voice_threads
from tests.fakes.fake_chat import FakeChatEngine, Say, Wait
from tests.fakes.voice import RecordingAudioOutput, ScriptedAudioInput, ScriptedStt, frames
from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tony.core.config.settings import load_config
from tony.core.guard.pin import PinStore
from tony.core.guard.unlock_expiry import UnlockExpiry
from tony.core.voice.service import VoiceService

UTTERANCE = frames("..SSSS" + "." * 22)

PIN = "4821"


async def test_start_constructs_session_with_unlock_expiry(tmp_path):
    home, _ = home_for(tmp_path, SHIPPED_POLICY_YAML)
    UnlockExpiry(home).refresh(lock_after_min=30)
    PinStore(home).set(PIN)

    async with Harness(home) as harness:
        assert harness.runtime.session.unlocked


async def test_list_devices_publishes_audio_devices_event(tmp_path, monkeypatch):
    home, _ = home_for(tmp_path)
    loader, voice = with_voice()
    monkeypatch.setattr(
        "tony.core.voice.engines.devices.list_devices",
        lambda: (),
    )

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        await harness.until(lambda: harness.of("audio_devices"))

    assert harness.of("audio_devices")[-1]["type"] == "audio_devices"


async def test_set_audio_device_applies_persists_and_republishes(tmp_path, monkeypatch):
    home, _ = home_for(tmp_path)
    loader, voice = with_voice()
    monkeypatch.setattr(
        "tony.core.voice.engines.devices.list_devices",
        lambda: (),
    )

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="set_audio_device", kind="input", device="Mic A")
        await harness.until(lambda: harness.of("audio_devices"))

    assert loader.audio.device == "Mic A"
    assert load_config(home).voice.input_device == "Mic A"
    assert harness.of("audio_devices")[-1]["selected_input"] == "Mic A"


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def with_voice(loader=None):
    loader = loader or FakeLoader()
    return loader, VoiceService(loader)


def states(harness):
    return [event["state"] for event in harness.of("voice_state")]


async def ready(harness):
    await harness.until(lambda: "ready" in states(harness))


async def test_events_reach_the_ui_and_the_voice_service(tmp_path):
    home, _ = home_for(tmp_path)
    loader, voice = with_voice()
    chat = FakeChatEngine([Say("Buenas tardes, señor.")])

    async with Harness(home, chat, voice=voice) as harness:
        await ready(harness)
        harness.send(type="send_message", text="Hola", origin="voice")
        await harness.until(lambda: loader.output.played == ["Buenas tardes, señor."])

    [turn] = harness.of("turn_started")
    assert (turn["origin"], turn["speaks"], turn["writes"]) == ("voice", True, False)
    assert loader.tts.calls == [("Buenas tardes, señor.", ALEX)]
    assert loader.calls[0][1] == (ALEX, "kokoro/ef_dora", EDITH)


async def test_listen_turns_an_utterance_into_a_voice_turn(tmp_path):
    home, _ = home_for(tmp_path)
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(UTTERANCE)
    loader.stt = ScriptedStt("¿Qué hora es?")
    _, voice = with_voice(loader)

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="listen")
        [turn] = await harness.wait_for("turn_started")

    assert [e["text"] for e in harness.of("transcript")] == ["¿Qué hora es?"]
    assert turn["origin"] == "voice"
    assert states(harness)[:4] == ["loading", "ready", "listening", "ready"]


async def test_stop_listening_is_routed(tmp_path):
    home, _ = home_for(tmp_path)
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames("..."))
    _, voice = with_voice(loader)

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="listen")
        await harness.until(lambda: states(harness)[-1] == "listening")
        harness.send(type="stop_listening")
        await harness.until(lambda: states(harness)[-1] == "ready")

    assert loader.audio.closed == 1


async def test_cancel_stops_speech_and_listening(tmp_path):
    home, _ = home_for(tmp_path)
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames("..."))
    loader.output = RecordingAudioOutput(blocking=True)
    _, voice = with_voice(loader)
    chat = FakeChatEngine([Say("Uno. Dos. "), Wait()])

    async with Harness(home, chat, voice=voice) as harness:
        await ready(harness)
        harness.send(type="send_message", text="Hola", origin="voice")
        await harness.until(lambda: loader.output.started.is_set())
        harness.send(type="cancel")
        await harness.until(lambda: loader.output.stops >= 1)
        assert voice.wait_silent(5)
        harness.send(type="listen")
        await harness.until(lambda: states(harness)[-1] == "listening")
        harness.send(type="cancel")
        await harness.until(lambda: states(harness)[-1] == "ready")

    assert loader.output.played == ["Uno."]
    assert loader.audio.closed == 1


async def test_without_voice_listen_reports_that_voice_is_not_configured(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        harness.send(type="listen")
        harness.send(type="stop_listening")
        harness.send(type="send_message", text="Hola")
        [turn] = await harness.wait_for("turn_started")

    [error] = harness.of("error")
    assert error["source"] == "listen" and "voice is not configured" in error["message"]
    assert (turn["speaks"], turn["writes"]) == (False, True)
    assert harness.of("voice_state") == []


async def test_stop_closes_the_voice_service(tmp_path):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()

    async with Harness(home, voice=voice) as harness:
        await ready(harness)

    assert voice_threads() == set()


async def test_a_voice_failure_never_hides_an_event_from_the_ui(tmp_path):
    home, _ = home_for(tmp_path)

    class Broken(VoiceService):
        def observe(self, event):
            if event["type"] == "token":
                raise RuntimeError("voz rota")

    voice = Broken(FakeLoader())

    async with Harness(home, FakeChatEngine([Say("Hola")]), voice=voice) as harness:
        harness.send(type="send_message", text="Hola")
        await harness.wait_for("result")

    assert [e["text"] for e in harness.of("token")] == ["Hola"]
    assert [(e["source"], e["message"]) for e in harness.of("error")] == [("voice", "voz rota")]


async def selected_device_event(tmp_path, monkeypatch, *, kind, device, unavailable=()):
    home, _ = home_for(tmp_path)
    loader, voice = with_voice()
    loader.audio.unavailable_devices = set(unavailable)
    loader.output.unavailable_devices = set(unavailable)
    monkeypatch.setattr("tony.core.voice.engines.devices.list_devices", lambda: ())

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="set_audio_device", kind=kind, device=device)
        await harness.until(lambda: harness.of("audio_devices"))
    return harness.of("audio_devices")[-1]


@pytest.mark.parametrize(
    ("kind", "warning", "other"),
    [
        ("input", "input_fallback_warning", "output_fallback_warning"),
        ("output", "output_fallback_warning", "input_fallback_warning"),
    ],
)
async def test_missing_device_publishes_the_fallback_warning_naming_it(
    tmp_path, monkeypatch, kind, warning, other
):
    event = await selected_device_event(
        tmp_path, monkeypatch, kind=kind, device="Foo", unavailable=["Foo"]
    )

    assert "Foo" in event[warning]
    assert event[other] is None


@pytest.mark.parametrize("kind", ["input", "output"])
async def test_found_device_publishes_no_warning(tmp_path, monkeypatch, kind):
    event = await selected_device_event(tmp_path, monkeypatch, kind=kind, device="Mic A")

    assert event["input_fallback_warning"] is None
    assert event["output_fallback_warning"] is None


@pytest.mark.parametrize("kind", ["input", "output"])
async def test_default_selection_publishes_no_warning(tmp_path, monkeypatch, kind):
    event = await selected_device_event(tmp_path, monkeypatch, kind=kind, device=None)

    assert event["input_fallback_warning"] is None
    assert event["output_fallback_warning"] is None
