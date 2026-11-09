import threading
import time

import pytest

from tests.fakes.voice import (
    RecordingMeter,
    ScriptedAudioInput,
    ScriptedStt,
    ThresholdVad,
    frames,
)
from tony.core.voice.listener import Listener

UTTERANCE = "..SSSS" + "." * 22


def test_listener_set_device_delegates_to_audio():
    audio = ScriptedAudioInput()
    listener = Listener(audio, ThresholdVad(), ScriptedStt(), lambda *_: None)
    listener.set_device("Mic B")
    assert audio.device == "Mic B"


class SteppingClock:
    """Each read advances `step` seconds, starting at 0."""

    def __init__(self, step: float) -> None:
        self.now = -step
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class Session:
    def __init__(self) -> None:
        self.transcripts: list[str] = []
        self.ended = threading.Event()

    def on_transcript(self, text):
        self.transcripts.append(text)

    def on_end(self):
        self.ended.set()


class Reports(list):
    def __call__(self, source, message):
        self.append((source, message))


@pytest.fixture
def make():
    listeners = []

    def build(audio, stt=None, clock=None, meter=None):
        reports = Reports()
        kwargs = {"clock": clock} if clock else {}
        if meter is not None:
            kwargs["meter"] = meter
        listener = Listener(audio, ThresholdVad(), stt or ScriptedStt(), reports, **kwargs)
        listener.start()
        listeners.append(listener)
        return listener, reports

    yield build
    for listener in listeners:
        listener.close()


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.005)
    return True


def listen(listener, idle=None):
    session = Session()
    listener.listen(session.on_transcript, session.on_end, idle_timeout_s=idle)
    return session


def test_one_utterance_is_transcribed_and_the_input_closed(make):
    audio = ScriptedAudioInput(frames(UTTERANCE + "SSS" + "." * 22))
    stt = ScriptedStt("  ¿Qué hora es?  ", "otra")
    listener, reports = make(audio, stt)
    session = listen(listener)
    assert session.ended.wait(5)
    assert session.transcripts == ["¿Qué hora es?"]
    assert (audio.opened, audio.closed, len(stt.pcms)) == (1, 1, 1)
    assert stt.pcms[0] == b"".join(frames("SSSS"))
    assert reports == [] and not listener.listening


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_transcript_posts_nothing_and_closes(make, text):
    audio = ScriptedAudioInput(frames(UTTERANCE))
    listener, _ = make(audio, ScriptedStt(text))
    session = listen(listener)
    assert session.ended.wait(5)
    assert session.transcripts == [] and audio.closed == 1


def test_no_speech_until_the_idle_timeout_closes_without_transcript(make):
    audio = ScriptedAudioInput(frames("." * 30))
    stt = ScriptedStt("nunca")
    listener, _ = make(audio, stt, clock=SteppingClock(0.5))
    session = listen(listener, idle=10)
    assert session.ended.wait(5)
    assert session.transcripts == [] and stt.pcms == [] and audio.closed == 1


def test_silence_shorter_than_the_idle_timeout_keeps_listening(make):
    audio = ScriptedAudioInput(frames("." * 19))
    listener, _ = make(audio, clock=SteppingClock(0.5))
    session = listen(listener, idle=10)
    assert not session.ended.wait(0.2)
    assert listener.listening and audio.closed == 0


def test_speech_disables_the_idle_timeout(make):
    audio = ScriptedAudioInput(frames("S" + "." * 21))
    listener, _ = make(audio, clock=SteppingClock(1))
    session = listen(listener, idle=10)
    assert not session.ended.wait(0.2)
    assert listener.listening


def test_without_idle_timeout_silence_keeps_listening(make):
    audio = ScriptedAudioInput(frames("." * 40))
    listener, _ = make(audio, clock=SteppingClock(1))
    session = listen(listener)
    assert not session.ended.wait(0.2)


def test_stop_closes_the_session(make):
    audio = ScriptedAudioInput(frames("..."))
    listener, _ = make(audio)
    session = listen(listener)
    listener.stop()
    assert session.ended.is_set()
    assert audio.closed == 1 and not listener.listening
    listener.stop()
    assert audio.closed == 1


def test_open_failure_reports_capture_and_ends(make):
    audio = ScriptedAudioInput(error=OSError("no input device"))
    listener, reports = make(audio)
    session = listen(listener)
    assert session.ended.wait(5)
    assert reports == [("voice.capture", "no input device")]
    assert not listener.listening


def test_stt_failure_reports_stt_and_ends(make):
    audio = ScriptedAudioInput(frames(UTTERANCE))
    listener, reports = make(audio, ScriptedStt(RuntimeError("modelo roto")))
    session = listen(listener)
    assert session.ended.wait(5)
    assert reports == [("voice.stt", "modelo roto")]
    assert session.transcripts == []


def test_a_new_session_starts_with_a_fresh_assembler(make):
    audio = ScriptedAudioInput(frames("SS"))
    stt = ScriptedStt("uno")
    listener, _ = make(audio, stt)
    first = listen(listener)
    listener.stop()
    assert first.ended.is_set()
    audio._frames = frames("S" + "." * 22)
    second = listen(listener)
    assert second.ended.wait(5)
    assert stt.pcms == [b"".join(frames("S"))]


def test_partial_frames_are_assembled_into_windows(make):
    data = b"".join(frames(UTTERANCE))
    audio = ScriptedAudioInput([data[i : i + 1000] for i in range(0, len(data), 1000)])
    stt = ScriptedStt("hola")
    listener, _ = make(audio, stt)
    session = listen(listener)
    assert session.ended.wait(5)
    assert stt.pcms == [b"".join(frames("SSSS"))]


def test_close_stops_the_threads(make):
    listener, _ = make(ScriptedAudioInput())
    listener.close()
    assert not any(t.name in {"tony-vad", "tony-stt"} for t in threading.enumerate())


def test_each_window_reports_its_level_and_the_utterance_clears_it(make):
    meter = RecordingMeter()
    audio = ScriptedAudioInput(frames(UTTERANCE + "SSS"))
    listener, _ = make(audio, ScriptedStt("hola"), meter=meter)
    session = listen(listener)
    assert session.ended.wait(5)
    levels = [entry[1] for entry in meter.log if entry[0] == "input"]
    assert levels == [0.0, 0.0, 1.0, 1.0, 1.0, 1.0] + [0.0] * 22
    assert meter.log[len(UTTERANCE)] == ("clear_input",)
    assert meter.sample(0.0) is None


def test_stop_clears_the_input_level(make):
    meter = RecordingMeter()
    listener, _ = make(ScriptedAudioInput(frames("SS")), meter=meter)
    listen(listener)
    assert wait_for(lambda: meter.sample(0.0) == ("input", 1.0))
    listener.stop()
    assert meter.sample(0.0) is None


def test_idle_timeout_clears_the_input_level(make):
    meter = RecordingMeter()
    audio = ScriptedAudioInput(frames("." * 30))
    listener, _ = make(audio, clock=SteppingClock(0.5), meter=meter)
    session = listen(listener, idle=10)
    assert session.ended.wait(5)
    assert meter.log[-1] == ("clear_input",)
    assert meter.sample(0.0) is None


def test_capture_error_clears_the_input_level(make):
    meter = RecordingMeter()
    meter.set_input(0.5)
    listener, _ = make(ScriptedAudioInput(error=OSError("no input device")), meter=meter)
    session = listen(listener)
    assert session.ended.wait(5)
    assert meter.sample(0.0) is None


class CountingSession(Session):
    def __init__(self) -> None:
        super().__init__()
        self.ends = 0

    def on_end(self):
        self.ends += 1
        super().on_end()


def test_utterance_of_a_cancelled_session_is_not_transcribed():
    stt = ScriptedStt("no debe oírse")
    listener = Listener(ScriptedAudioInput(), ThresholdVad(), stt, Reports())
    session = CountingSession()
    listener.listen(session.on_transcript, session.on_end)
    listener._transcription.put((listener._session, b"pcm"))
    listener.stop()

    listener.start()
    listener.close()

    assert stt.pcms == []
    assert session.transcripts == []
    assert session.ends == 1


def test_cancel_during_inference_discards_the_transcript_and_ends_once(make):
    inferring, release = threading.Event(), threading.Event()

    class BlockingStt:
        def transcribe(self, pcm):
            inferring.set()
            release.wait(5)
            return "tarde"

    listener, _ = make(ScriptedAudioInput(frames(UTTERANCE + "SSS" + "." * 22)), BlockingStt())
    session = CountingSession()
    listener.listen(session.on_transcript, session.on_end)
    assert inferring.wait(5)

    listener.stop()
    release.set()
    listener.close()

    assert session.transcripts == []
    assert session.ends == 1


def test_listener_set_device_reports_the_audio_result():
    audio = ScriptedAudioInput()
    audio.unavailable_devices = {"Ghost"}
    listener = Listener(audio, ThresholdVad(), ScriptedStt(), lambda *_: None)

    assert listener.set_device("Mic B") is True
    assert listener.set_device("Ghost") is False
