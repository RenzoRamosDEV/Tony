import asyncio
import threading

import pytest

from tests.core.voice.service_harness import FakeLoader, Harness, voice_threads
from tests.fakes.voice import RealtimeAudioOutput, ScriptedAudioInput, ToneTts, frames
from tony.core.events import core_events as ev


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


def levels(h, source):
    return [e for e in h.of_type("voice_level") if e["source"] == source]


async def test_listening_for_one_second_publishes_input_levels(harness):
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames("." * 31))
    h = harness(loader)
    h.start()
    await h.ready()
    h.service.listen()
    await asyncio.sleep(1.0)
    h.service.stop_listening()
    await h.until(lambda: h.states()[-1] == ("ready", None))
    events = levels(h, "input")
    assert 15 <= len(events) <= 25
    assert all(set(e) == {"type", "ts", "source", "level"} for e in events)
    assert all(e["level"] == 0.0 for e in events)
    await asyncio.sleep(0.2)
    assert len(levels(h, "input")) == len(events)


async def test_speaking_publishes_output_levels_only_while_playing(harness):
    loader = FakeLoader()
    loader.tts = ToneTts(seconds=1.0, amplitude=0.05)
    loader.output = RealtimeAudioOutput()
    h = harness(loader)
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Hola."), ev.turn_result("jarvis", "Hola.", "auto"))
    await h.until(loader.output.finished.is_set)
    await asyncio.sleep(0.1)
    events = levels(h, "output")
    assert 15 <= len(events) <= 25
    assert {e["level"] for e in events} == {0.25}
    await asyncio.sleep(0.3)
    assert len(levels(h, "output")) == len(events)
    assert levels(h, "input") == []


async def test_stopped_speech_publishes_no_more_output_levels(harness):
    loader = FakeLoader()
    loader.tts = ToneTts(seconds=3.0)
    loader.output = RealtimeAudioOutput()
    h = harness(loader)
    h.start()
    await h.ready()
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Hola."), ev.turn_result("jarvis", "Hola.", "auto"))
    await h.until(lambda: levels(h, "output") != [])
    h.service.stop_speaking()
    await asyncio.sleep(0.1)
    count = len(levels(h, "output"))
    await asyncio.sleep(0.3)
    assert len(levels(h, "output")) == count


async def test_ready_and_idle_publishes_no_level(harness):
    h = harness()
    h.start()
    await h.ready()
    await asyncio.sleep(0.5)
    assert h.of_type("voice_level") == []


async def test_level_interval_is_injectable(harness):
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames("."))
    h = harness(loader, level_interval_s=0.01)
    h.start()
    await h.ready()
    h.service.listen()
    await h.until(lambda: len(levels(h, "input")) >= 20, timeout=2)


async def test_close_leaves_no_level_thread(harness):
    h = harness()
    h.start()
    await h.ready()
    assert "tony-level" in {t.name for t in threading.enumerate()}
    h.service.close()
    assert "tony-level" not in {t.name for t in threading.enumerate()}
