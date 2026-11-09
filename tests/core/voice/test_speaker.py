import threading

import pytest

from tests.fakes.voice import RecordingAudioOutput, RecordingMeter, TextTts
from tony.core.voice.speaker import Speaker

ALEX = "kokoro/em_alex"
DORA = "kokoro/ef_dora,bf_emma"


def test_speaker_set_device_delegates_to_output():
    output = RecordingAudioOutput()
    speaker = Speaker(TextTts(), output, lambda *_: None)
    speaker.set_device("Speak B")
    assert output.device == "Speak B"


def test_speaker_set_device_reports_the_output_result():
    output = RecordingAudioOutput()
    output.unavailable_devices = {"Ghost"}
    speaker = Speaker(TextTts(), output, lambda *_: None)

    assert speaker.set_device("Speak B") is True
    assert speaker.set_device("Ghost") is False


class Reports(list):
    def __call__(self, source, message):
        self.append((source, message))


@pytest.fixture
def make():
    speakers = []

    def build(tts=None, output=None, meter=None):
        reports = Reports()
        kwargs = {} if meter is None else {"meter": meter}
        speaker = Speaker(tts or TextTts(), output or RecordingAudioOutput(), reports, **kwargs)
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


class LoggingOutput(RecordingAudioOutput):
    def __init__(self, log, **kwargs):
        super().__init__(**kwargs)
        self.log = log

    def play(self, clip):
        self.log.append(("play", clip.pcm.decode("utf-8")))
        super().play(clip)


def test_clip_envelope_starts_before_play_and_stops_after_it(make):
    log = []
    speaker, _ = make(output=LoggingOutput(log), meter=RecordingMeter(log))
    speaker.say("Uno.", ALEX)
    assert speaker.wait_drained(5)
    assert log == [("start_output", 1), ("play", "Uno."), ("stop_output",)]


def test_playback_error_stops_the_envelope(make):
    log = []
    meter = RecordingMeter(log)
    speaker, _ = make(output=LoggingOutput(log, fail_on={"Uno."}), meter=meter)
    speaker.say("Uno.", ALEX)
    assert speaker.wait_drained(5)
    assert log[-1] == ("stop_output",)
    assert meter.sample(0.0) is None


def test_stop_speaking_stops_the_envelope(make):
    log = []
    meter = RecordingMeter(log)
    output = RecordingAudioOutput(blocking=True)
    speaker, _ = make(output=output, meter=meter)
    speaker.say("Uno.", ALEX)
    assert output.started.wait(5)
    log.clear()
    speaker.stop_speaking()
    assert log[0] == ("stop_output",)
