import threading

import pytest

from tests.core.voice.service_harness import (
    ALEX,
    DORA,
    EDITH,
    FakeLoader,
    Harness,
    voice_threads,
)
from tests.fakes.voice import RecordingAudioOutput, ScriptedAudioInput, ScriptedStt, frames
from tony.core.config.settings import VoiceSettings
from tony.core.events import core_events as ev
from tony.core.events.messages import TaskResult
from tony.core.voice.ports import Unavailable
from tony.core.voice.service import VoiceCast

UTTERANCE = frames("..SSSS" + "." * 22)


@pytest.fixture
async def harness():
    made = []

    def build(loader=None, **options):
        h = Harness(loader or FakeLoader(), **options)
        made.append(h)
        return h

    yield build
    for h in made:
        h.service.close()
    assert voice_threads() == set()


async def test_preload_publishes_loading_then_ready_and_loads_each_voice_once(harness):
    h = harness()
    h.start()
    await h.ready()
    assert h.states() == [("loading", None), ("ready", None)]
    assert h.loader.calls == [(VoiceSettings(), (ALEX, DORA, EDITH))]
    assert h.service.ready


async def test_shared_voices_are_loaded_once(harness):
    h = harness()
    h.start(cast=VoiceCast(front="jarvis", front_voice=ALEX, worker_voice=ALEX, guard_voice=ALEX))
    await h.ready()
    assert h.loader.calls[0][1] == (ALEX,)


async def test_not_ready_while_loading():
    gate = threading.Event()
    h = Harness(FakeLoader(gate=gate))
    h.start()
    assert h.states() == [("loading", None)] and not h.service.ready
    gate.set()
    await h.ready()
    h.service.close()


async def test_loader_unavailable_reports_its_reason(harness):
    h = harness(FakeLoader(Unavailable("voice extra not installed")))
    h.start()
    await h.until(lambda: len(h.states()) == 2)
    assert h.states()[1] == ("unavailable", "voice extra not installed")
    assert not h.service.ready


async def test_loader_failure_makes_voice_unavailable(harness):
    h = harness(FakeLoader(RuntimeError("model corrupt")))
    h.start()
    await h.until(lambda: len(h.states()) == 2)
    assert h.states()[1] == ("unavailable", "model corrupt")


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        (VoiceSettings(stt="vosk/es"), "voice.stt"),
        (VoiceSettings(stt="faster-whisper/"), "voice.stt"),
        (VoiceSettings(vad="webrtc"), "voice.vad"),
    ],
)
async def test_unsupported_settings_make_voice_unavailable(harness, settings, field):
    h = harness()
    h.start(settings)
    await h.until(lambda: len(h.states()) == 2)
    state, reason = h.states()[1]
    assert state == "unavailable" and field in reason
    assert h.loader.calls == []


async def test_listen_while_loading_starts_once_ready(harness):
    gate = threading.Event()
    loader = FakeLoader(gate=gate)
    loader.audio = ScriptedAudioInput(UTTERANCE)
    loader.stt = ScriptedStt("Hola")
    h = harness(loader)
    h.start()
    h.service.listen()
    assert loader.audio.opened == 0
    gate.set()
    await h.until(lambda: h.commands)
    assert loader.audio.opened == 1


async def test_listen_when_unavailable_publishes_a_listen_error(harness):
    h = harness(FakeLoader(Unavailable("voice extra not installed")))
    h.start()
    await h.until(lambda: len(h.states()) == 2)
    h.service.listen()
    [error] = h.of_type("error")
    assert (error["source"], error["message"]) == ("listen", "voice extra not installed")


async def test_listening_publishes_the_transcript_and_sends_a_voice_message(harness):
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(UTTERANCE)
    loader.stt = ScriptedStt("¿Qué hora es?")
    h = harness(loader)
    h.start()
    await h.ready()
    h.service.listen()
    await h.until(lambda: h.states()[-1] == ("ready", None) and len(h.states()) == 4)
    assert h.states()[2:] == [("listening", None), ("ready", None)]
    assert [e["text"] for e in h.of_type("transcript")] == ["¿Qué hora es?"]
    assert h.commands == [{"type": "send_message", "text": "¿Qué hora es?", "origin": "voice"}]
    assert loader.audio.closed == 1


async def test_capture_failure_reports_and_returns_to_ready(harness):
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(error=OSError("no input device"))
    h = harness(loader)
    h.start()
    await h.ready()
    h.service.listen()
    await h.until(lambda: h.of_type("error"))
    await h.until(lambda: h.states()[-1] == ("ready", None) and len(h.states()) == 4)
    assert h.of_type("error")[0]["source"] == "voice.capture"


async def test_stop_listening_closes_the_session(harness):
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames("..."))
    h = harness(loader)
    h.start()
    await h.ready()
    h.service.listen()
    h.service.listen()
    assert loader.audio.opened == 1
    h.service.stop_listening()
    await h.until(lambda: h.states()[-1] == ("ready", None) and len(h.states()) == 4)
    assert loader.audio.closed == 1 and h.commands == []


async def test_idle_timeout_closes_a_message_session(harness):
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames("." * 3))
    h = harness(loader, idle_timeout_s=0)
    h.start()
    await h.ready()
    h.service.listen()
    await h.until(lambda: len(h.states()) == 4)
    assert h.commands == []


async def test_speaking_turn_plays_sentences_with_the_front_voice_before_the_result(harness):
    h = harness()
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Buenas tardes, señor."), ev.token("jarvis", " Hace"))
    await h.until(lambda: h.loader.output.played == ["Buenas tardes, señor."])
    h.observe(ev.token("jarvis", " sol."), ev.turn_result("jarvis", "x", "auto"))
    await h.until(lambda: len(h.loader.output.played) == 2)
    assert h.loader.output.played == ["Buenas tardes, señor.", "Hace sol."]
    assert {voice for _, voice in h.loader.tts.calls} == {ALEX}


async def test_a_finished_sentence_is_spoken_when_the_stream_pauses(harness):
    h = harness(flush_after_s=0.01)
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Voy a ello."))
    await h.until(lambda: h.loader.output.played == ["Voy a ello."])


async def test_progress_is_spoken_in_a_speaking_turn(harness):
    h = harness()
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(
        ev.token("jarvis", "Delego."), ev.progress("jarvis", "Un momento, señor; estoy en ello.")
    )
    await h.until(lambda: len(h.loader.output.played) == 2)
    assert h.loader.output.played == ["Delego.", "Un momento, señor; estoy en ello."]
    assert h.loader.tts.calls[1] == ("Un momento, señor; estoy en ello.", ALEX)


async def test_non_speaking_turn_speaks_nothing(harness):
    h = harness()
    h.start()
    await h.ready()
    h.speaking_turn(speaks=False)
    h.observe(
        ev.token("jarvis", "Hola. Adiós."),
        ev.progress("jarvis", "Un momento."),
        ev.turn_result("jarvis", "Hola. Adiós.", "text"),
    )
    assert h.service.wait_silent(1)
    assert h.loader.tts.calls == []


async def test_speech_before_ready_is_skipped(harness):
    gate = threading.Event()
    h = harness(FakeLoader(gate=gate))
    h.start()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Hola. "), ev.turn_result("jarvis", "Hola.", "voice"))
    gate.set()
    await h.ready()
    assert h.loader.tts.calls == []


async def test_front_error_stops_the_speech(harness):
    loader = FakeLoader()
    loader.output = RecordingAudioOutput(blocking=True)
    h = harness(loader)
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Uno. Dos. "))
    assert loader.output.started.wait(5)
    h.observe(ev.error("front", "model down"), ev.token("jarvis", "Tres. "))
    assert loader.output.stops == 1
    assert h.service.wait_silent(5)
    assert loader.output.played == ["Uno."]


async def test_other_errors_do_not_stop_the_speech(harness):
    h = harness()
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.error("voice.tts", "x"), ev.token("jarvis", "Uno. "))
    await h.until(lambda: h.loader.output.played == ["Uno."])


async def test_listen_stops_playback_before_opening_the_microphone(harness):
    loader = FakeLoader()
    loader.output = RecordingAudioOutput(blocking=True)
    stops_at_open = []

    class Input(ScriptedAudioInput):
        def open(self, on_frame):
            stops_at_open.append(loader.output.stops)
            super().open(on_frame)

    loader.audio = Input()
    h = harness(loader)
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Uno. Dos. "))
    assert loader.output.started.wait(5)
    h.service.listen()
    assert stops_at_open == [1]
    h.observe(ev.token("jarvis", "Tres. "))
    assert h.service.wait_silent(5)
    assert loader.output.played == ["Uno."]


async def test_stop_speaking_discards_the_turn(harness):
    loader = FakeLoader()
    loader.output = RecordingAudioOutput(blocking=True)
    h = harness(loader)
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Uno. "))
    assert loader.output.started.wait(5)
    h.service.stop_speaking()
    h.observe(ev.token("jarvis", "Dos. "))
    assert h.service.wait_silent(5)
    assert loader.output.played == ["Uno."]


async def test_close_leaves_no_voice_thread(harness):
    h = harness()
    h.start()
    await h.ready()
    h.service.close()
    assert voice_threads() == set()


async def test_close_before_start_and_twice_is_harmless(harness):
    harness().service.close()
    h = harness()
    h.start()
    await h.ready()
    h.service.close()
    h.service.close()
    assert voice_threads() == set()


async def test_task_events_do_not_disturb_a_turn(harness):
    h = harness()
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(
        ev.token("jarvis", "Hecho"),
        ev.task_started("t1", "viernes", "o"),
        ev.task_result(
            "t1",
            "viernes",
            "ok",
            TaskResult(resumen="r"),
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=0,
        ),
        ev.token("jarvis", ", señor."),
        ev.turn_result("jarvis", "Hecho, señor.", "voice"),
    )
    await h.until(lambda: h.loader.output.played == ["Hecho, señor."])
