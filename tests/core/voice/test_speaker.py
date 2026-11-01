import threading

import pytest

from tests.fakes.voice import RecordingAudioOutput, TextTts
from tony.core.voice.speaker import Speaker

ALEX = "kokoro/em_alex"
DORA = "kokoro/ef_dora,bf_emma"


class Reports(list):
    def __call__(self, source, message):
        self.append((source, message))


@pytest.fixture
def make():
    speakers = []

    def build(tts=None, output=None):
        reports = Reports()
        speaker = Speaker(tts or TextTts(), output or RecordingAudioOutput(), reports)
        speaker.start()
        speakers.append(speaker)
        return speaker, reports

    yield build
    for speaker in speakers:
        speaker.close()


def test_sentences_are_played_in_order_with_their_voice(make):
    tts, output = TextTts(), RecordingAudioOutput()
    speaker, _ = make(tts, output)
    speaker.say("Uno.", ALEX)
    speaker.say("Dos.", DORA)
    assert speaker.wait_drained(5)
    assert output.played == ["Uno.", "Dos."]
    assert tts.calls == [("Uno.", ALEX), ("Dos.", DORA)]
    assert output.rates == [24_000, 24_000]


def test_synthesis_failure_is_reported_and_the_next_sentence_played(make):
    output = RecordingAudioOutput()
    speaker, reports = make(TextTts(fail_on={"Dos."}), output)
    for text in ("Uno.", "Dos.", "Tres."):
        speaker.say(text, ALEX)
    assert speaker.wait_drained(5)
    assert output.played == ["Uno.", "Tres."]
    assert reports == [("voice.tts", "cannot synthesise Dos.")]


def test_playback_failure_is_reported_and_the_next_sentence_played(make):
    output = RecordingAudioOutput(fail_on={"Uno."})
    speaker, reports = make(output=output)
    speaker.say("Uno.", ALEX)
    speaker.say("Dos.", ALEX)
    assert speaker.wait_drained(5)
    assert output.played == ["Dos."]
    assert reports == [("voice.playback", "cannot play Uno.")]


def test_stop_speaking_interrupts_playback_and_drops_queued_sentences(make):
    output = RecordingAudioOutput(blocking=True)
    speaker, _ = make(output=output)
    for text in ("Uno.", "Dos.", "Tres."):
        speaker.say(text, ALEX)
    assert output.started.wait(5)
    speaker.stop_speaking()
    assert output.stops == 1
    assert speaker.wait_drained(5)
    output.started.clear()
    speaker.say("Nuevo.", ALEX)
    assert output.started.wait(5)
    output.release()
    assert speaker.wait_drained(5)
    assert output.played == ["Uno.", "Nuevo."]


def test_drained_when_idle_and_callbacks_fire_once_drained(make):
    output = RecordingAudioOutput(blocking=True)
    speaker, _ = make(output=output)
    assert speaker.wait_drained(0)
    fired = threading.Event()
    speaker.on_drained(fired.set)
    assert fired.is_set()
    fired.clear()
    speaker.say("Uno.", ALEX)
    speaker.on_drained(fired.set)
    assert output.started.wait(5)
    assert not speaker.wait_drained(0.05)
    assert not fired.is_set()
    output.release()
    assert fired.wait(5)


def test_close_stops_the_threads(make):
    speaker, _ = make()
    speaker.close()
    assert not any(t.name in {"tony-tts", "tony-playback"} for t in threading.enumerate())
