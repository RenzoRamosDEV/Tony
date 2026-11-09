import threading

import pytest

from tests.core.voice.service_harness import FakeLoader, Harness, voice_threads
from tests.fakes.voice import (
    RecordingAudioOutput,
    ScriptedAudioInput,
    ScriptedStt,
    TextTts,
    ThresholdVad,
    frames,
)
from tony.core.events import core_events as ev
from tony.core.voice.listener import Listener
from tony.core.voice.speaker import Speaker
from tony.core.voice.timing import MARKS, StageTimings

UTTERANCE = "..SSSS" + "." * 22


class Ticking:
    def __init__(self) -> None:
        self.now = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            self.now += 1.0
            return self.now


def only_turn(timings: StageTimings) -> dict[str, float]:
    (marks,) = timings.turns().values()
    return marks


def ordered(marks: dict[str, float], names) -> bool:
    values = [marks[name] for name in names]
    return values == sorted(values)


def listen_once(timings, stt=None):
    audio = ScriptedAudioInput(frames(UTTERANCE))
    kwargs = {} if timings is None else {"timings": timings}
    listener = Listener(
        audio, ThresholdVad(), stt or ScriptedStt("hola"), lambda *_: None, **kwargs
    )
    listener.start()
    done = threading.Event()
    texts: list[str] = []
    listener.listen(texts.append, done.set)
    assert done.wait(5)
    listener.close()
    return listener, texts


def test_listener_marks_speech_end_capture_close_and_stt_in_order():
    timings = StageTimings(clock=Ticking())
    listener, texts = listen_once(timings)

    marks = only_turn(timings)
    assert texts == ["hola"]
    assert set(marks) == {"speech_end", "capture_close", "stt_start", "stt_end"}
    assert ordered(marks, ["speech_end", "capture_close", "stt_start", "stt_end"])
    assert listener.turn is not None


def test_listener_speech_end_is_the_last_speech_window_not_the_endpointing_close():
    timings = StageTimings(clock=Ticking())
    listen_once(timings)
    marks = only_turn(timings)
    assert marks["speech_end"] < marks["capture_close"]


def test_listener_speech_end_is_the_clock_at_the_last_speech_window():
    timings = StageTimings(clock=Ticking())
    listen_once(timings)
    marks = only_turn(timings)
    assert (marks["speech_end"], marks["capture_close"]) == (4.0, 5.0)


def test_listener_without_a_recorder_behaves_unchanged():
    listener, texts = listen_once(None)
    assert texts == ["hola"]
    assert listener.turn is None


def test_listener_without_speech_starts_no_turn():
    timings = StageTimings()
    audio = ScriptedAudioInput(frames("." * 10))
    listener = Listener(audio, ThresholdVad(), ScriptedStt(), lambda *_: None, timings=timings)
    listener.start()
    done = threading.Event()
    listener.listen(lambda _: None, done.set, idle_timeout_s=0)
    assert done.wait(5)
    listener.close()
    assert timings.turns() == {}


def test_speaker_marks_synthesis_and_playback_for_a_turn():
    timings = StageTimings(clock=Ticking())
    output = RecordingAudioOutput()
    speaker = Speaker(TextTts(), output, lambda *_: None, timings=timings)
    speaker.start()
    turn = timings.begin_turn()
    speaker.say("hola", "v", turn=turn)
    assert speaker.wait_drained(5)
    speaker.close()

    marks = timings.turns()[turn]
    assert set(marks) == {"synthesis_start", "synthesis_end", "playback_start"}
    assert ordered(marks, ["synthesis_start", "synthesis_end", "playback_start"])


def test_speaker_marks_only_the_first_sentence_of_a_turn():
    timings = StageTimings(clock=Ticking())
    speaker = Speaker(TextTts(), RecordingAudioOutput(), lambda *_: None, timings=timings)
    speaker.start()
    turn = timings.begin_turn()
    speaker.say("uno", "v", turn=turn)
    speaker.say("dos", "v", turn=turn)
    assert speaker.wait_drained(5)
    speaker.close()
    marks = timings.turns()[turn]
    assert set(marks) == {"synthesis_start", "synthesis_end", "playback_start"}
    assert ordered(marks, ["synthesis_start", "synthesis_end", "playback_start"])


def test_speaker_sentences_without_a_turn_record_nothing():
    timings = StageTimings()
    output = RecordingAudioOutput()
    speaker = Speaker(TextTts(), output, lambda *_: None, timings=timings)
    speaker.start()
    speaker.say("hola", "v")
    assert speaker.wait_drained(5)
    speaker.close()
    assert output.played == ["hola"]
    assert timings.turns() == {}


@pytest.fixture
async def harness():
    made = []

    def build(loader, **options):
        h = Harness(loader, **options)
        made.append(h)
        return h

    yield build
    for h in made:
        h.service.close()
    assert voice_threads() == set()


def voice_loader() -> FakeLoader:
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(frames(UTTERANCE))
    loader.stt = ScriptedStt("hola")
    return loader


async def run_voice_turn(h: Harness) -> None:
    h.start()
    await h.ready()
    h.service.listen()
    await h.until(lambda: h.commands)
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Buenas tardes."))
    h.observe(ev.turn_result("jarvis", "Buenas tardes.", "auto"))
    await h.until(lambda: h.service.wait_silent(0.01) and h.loader.output.played)


async def test_service_records_all_eight_marks_in_order(harness):
    timings = StageTimings(clock=Ticking())
    h = harness(voice_loader(), timings=timings)
    await run_voice_turn(h)

    marks = only_turn(timings)
    assert set(marks) == set(MARKS)
    assert ordered(marks, ["speech_end", "capture_close", "stt_start", "stt_end"])
    assert ordered(marks, ["stt_end", "first_token", "synthesis_start"])
    assert ordered(marks, ["synthesis_start", "synthesis_end", "playback_start"])


async def test_service_without_a_recorder_plays_the_same(harness):
    h = harness(voice_loader())
    await run_voice_turn(h)
    assert h.loader.output.played == ["Buenas tardes."]
    assert h.commands[0]["text"] == "hola"


async def test_typed_messages_after_a_voice_turn_are_not_recorded(harness):
    timings = StageTimings(clock=Ticking())
    h = harness(voice_loader(), timings=timings)
    await run_voice_turn(h)
    before = timings.turns()

    h.speaking_turn()
    h.observe(ev.token("jarvis", "Otra cosa."), ev.turn_result("jarvis", "Otra cosa.", "auto"))
    await h.until(lambda: len(h.loader.output.played) == 2)
    assert timings.turns() == before
