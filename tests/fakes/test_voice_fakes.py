import threading

import pytest

from tests.fakes.voice import (
    RecordingAudioOutput,
    ScriptedAudioInput,
    ScriptedStt,
    TextTts,
    ThresholdVad,
    frames,
    window,
)
from tony.core.voice.ports import WINDOW_BYTES, Clip


def test_frames_are_full_windows_classified_by_the_threshold_vad():
    vad = ThresholdVad()
    assert all(len(frame) == WINDOW_BYTES for frame in frames("S."))
    assert [vad.is_speech(frame) for frame in frames("S.S")] == [True, False, True]
    vad.reset()
    assert vad.resets == 1


def test_scripted_input_delivers_frames_on_open_and_counts_close():
    audio = ScriptedAudioInput([window(True), window(False)])
    got = []
    audio.open(got.append)
    audio.close()
    assert (len(got), audio.opened, audio.closed) == (2, 1, 1)


def test_scripted_input_can_fail_to_open():
    audio = ScriptedAudioInput(error=OSError("no device"))
    with pytest.raises(OSError):
        audio.open(lambda frame: None)
    assert audio.opened == 1


def test_scripted_stt_returns_raises_then_defaults_to_empty():
    stt = ScriptedStt("hola", RuntimeError("boom"))
    assert stt.transcribe(b"a") == "hola"
    with pytest.raises(RuntimeError):
        stt.transcribe(b"b")
    assert stt.transcribe(b"c") == ""
    assert stt.pcms == [b"a", b"b", b"c"]


def test_text_tts_encodes_the_text_and_fails_on_request():
    tts = TextTts(fail_on={"mal"})
    assert tts.synthesize("Hola.", "kokoro/em_alex") == Clip(b"Hola.")
    with pytest.raises(RuntimeError):
        tts.synthesize("mal", "kokoro/em_alex")
    assert tts.calls == [("Hola.", "kokoro/em_alex"), ("mal", "kokoro/em_alex")]


def test_recording_output_records_and_fails_on_request():
    output = RecordingAudioOutput(fail_on={"mal"})
    output.play(Clip(b"uno"))
    with pytest.raises(RuntimeError):
        output.play(Clip(b"mal"))
    assert (output.played, output.rates) == (["uno"], [24_000])


def test_blocking_output_waits_until_stopped():
    output = RecordingAudioOutput(blocking=True)
    worker = threading.Thread(target=output.play, args=(Clip(b"uno"),))
    worker.start()
    assert output.started.wait(5)
    assert worker.is_alive()
    output.stop()
    worker.join(5)
    assert not worker.is_alive() and output.stops == 1


def test_scripted_input_sessions_deliver_one_list_per_open():
    audio = ScriptedAudioInput(sessions=[[window(True)], [window(False), window(False)]])
    got = []
    for _ in range(3):
        audio.open(got.append)
    assert len(got) == 3 and audio.opened == 3
