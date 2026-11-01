from tony.core.voice.ports import WINDOW_MS
from tony.core.voice.utterances import END_SILENCE_MS, MAX_UTTERANCE_MS, UtteranceAssembler

SPEECH = b"S"
SILENCE = b"."


def feed(assembler, pattern):
    """Push one window per character of `pattern` (`S` speech, `.` silence)."""
    produced = []
    for mark in pattern:
        found = assembler.push(mark.encode(), mark == "S")
        if found is not None:
            produced.append(found)
    return produced


def test_thresholds_follow_the_spec():
    assert (WINDOW_MS, END_SILENCE_MS, MAX_UTTERANCE_MS) == (32, 700, 30_000)


def test_twenty_two_silent_windows_close_the_utterance():
    speech = "S" * 31
    assert feed(UtteranceAssembler(), speech + "." * 22) == [speech.encode()]


def test_twenty_one_silent_windows_do_not_close_it():
    assert feed(UtteranceAssembler(), "S" * 31 + "." * 21) == []


def test_closing_happens_on_the_twenty_second_window_exactly():
    assembler = UtteranceAssembler()
    assert feed(assembler, "S" + "." * 21) == []
    assert feed(assembler, ".") == [b"S"]


def test_short_pause_keeps_one_utterance():
    pattern = "SS" + "." * 20 + "SS"
    assert feed(UtteranceAssembler(), pattern + "." * 22) == [pattern.encode()]


def test_leading_and_trailing_silence_excluded():
    assert feed(UtteranceAssembler(), "." * 5 + "SS.S" + "." * 22) == [b"SS.S"]


def test_silence_only_produces_nothing():
    assert feed(UtteranceAssembler(), "." * 2000) == []


def test_speech_is_cut_at_thirty_seconds_and_the_rest_starts_a_new_utterance():
    assembler = UtteranceAssembler()
    assert feed(assembler, "S" * 937) == []
    assert feed(assembler, "S") == [b"S" * 938]
    assert feed(assembler, "S" * 312 + "." * 22) == [b"S" * 312]


def test_cut_counts_inner_silence_in_the_duration():
    pattern = "S" + "." * 20 + "S" * 917
    assert feed(UtteranceAssembler(), pattern) == [pattern.encode()]


def test_assembler_is_reusable_after_an_utterance():
    assembler = UtteranceAssembler()
    assert feed(assembler, "S" + "." * 22 + "SS" + "." * 22) == [b"S", b"SS"]


def test_reset_drops_the_open_utterance():
    assembler = UtteranceAssembler()
    feed(assembler, "SSS")
    assembler.reset()
    assert feed(assembler, "." * 22) == []
    assert not assembler.in_speech


def test_in_speech_reports_an_open_utterance():
    assembler = UtteranceAssembler()
    assert not assembler.in_speech
    feed(assembler, "S")
    assert assembler.in_speech
