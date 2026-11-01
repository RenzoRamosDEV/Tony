import threading

import pytest

from tests.fakes.voice import ScriptedAudioInput, ScriptedStt, ThresholdVad, frames
from tony.core.voice.listener import Listener

UTTERANCE = "..SSSS" + "." * 22


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

    def build(audio, stt=None, clock=None):
        reports = Reports()
        kwargs = {"clock": clock} if clock else {}
        listener = Listener(audio, ThresholdVad(), stt or ScriptedStt(), reports, **kwargs)
        listener.start()
        listeners.append(listener)
        return listener, reports

    yield build
    for listener in listeners:
        listener.close()


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
