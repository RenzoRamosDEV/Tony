from pathlib import Path

import pytest

from tony.core.voice.spoken import (
    LONG_REPLY_CHARS,
    SCREEN_PHRASE,
    LongReplyGate,
    SpokenFilter,
    TurnSpeech,
    spoken_text,
)

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "spoken"
CASES = sorted(path.stem for path in GOLDEN.glob("*.md"))


def golden(name):
    reply = (GOLDEN / f"{name}.md").read_text(encoding="utf-8").removesuffix("\n")
    spoken = (GOLDEN / f"{name}.spoken").read_text(encoding="utf-8").splitlines()
    return reply, spoken


def speak(chunks, voice="kokoro/em_alex"):
    said = []
    speech = TurnSpeech(voice, lambda text, used: said.append((text, used)))
    for chunk in chunks:
        speech.feed(chunk)
    speech.finish()
    assert {used for _, used in said} <= {voice}
    return [text for text, _ in said]


def test_golden_cases_exist():
    assert len(CASES) >= 9


@pytest.mark.parametrize("name", CASES)
def test_golden_spoken_items_whole_reply(name):
    reply, spoken = golden(name)
    assert speak([reply]) == spoken


@pytest.mark.parametrize("name", CASES)
def test_golden_spoken_items_one_character_at_a_time(name):
    reply, spoken = golden(name)
    assert speak(list(reply)) == spoken


@pytest.mark.parametrize(
    ("name", "length"), [("long_600", 600), ("long_601", 601), ("long_900", 900)]
)
def test_boundary_fixtures_have_their_exact_length(name, length):
    assert len(golden(name)[0]) == length


def test_constants():
    assert (LONG_REPLY_CHARS, SCREEN_PHRASE) == (600, "Te lo dejo en pantalla.")


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        (
            "Es **muy** importante: ver [la guía](https://x.test).",
            "Es muy importante: ver la guía.",
        ),
        ("_x_ y __y__", "x y y"),
        ("### Título", "Título"),
        ("- item", "item"),
        ("+ item", "item"),
        ("12) paso", "paso"),
        ("Use `cmd` ya", "Use cmd ya"),
        ("archivo notas_viejas.md y 2*3*4", "archivo notas_viejas.md y 2*3*4"),
        ("**", ""),
        ("1.", ""),
        ("Sin marcas.", "Sin marcas."),
    ],
)
def test_spoken_text_strips_markup(raw, spoken):
    assert spoken_text(raw) == spoken


def test_filter_collapses_consecutive_phrases_but_not_separated_ones():
    spoken_filter = SpokenFilter()
    items = ["| a |", "```", "x", "```", "| b |", "Hola.", "| c |", "**", "| d |"]
    out = [said for item in items for said in spoken_filter.push(item)]
    assert out == [SCREEN_PHRASE, "Hola.", SCREEN_PHRASE]


def test_gate_releases_held_items_up_to_the_limit():
    gate = LongReplyGate()
    assert gate.push("uno") == ["uno"]
    assert gate.push("dos") == ["dos"]
    assert gate.push("tres") == []
    assert gate.finish(LONG_REPLY_CHARS) == ["tres"]


def test_gate_drops_held_items_beyond_the_limit_and_adds_the_phrase():
    gate = LongReplyGate()
    for item in ("uno", "dos", "tres"):
        gate.push(item)
    assert gate.finish(LONG_REPLY_CHARS + 1) == [SCREEN_PHRASE]


def test_gate_does_not_repeat_the_phrase():
    gate = LongReplyGate()
    gate.push("uno")
    gate.push(SCREEN_PHRASE)
    gate.push("tres")
    assert gate.finish(900) == []


def test_short_long_reply_with_few_items_still_ends_with_the_phrase():
    gate = LongReplyGate()
    gate.push("uno")
    assert gate.finish(700) == [SCREEN_PHRASE]


def test_turn_speech_uses_its_voice_and_flushes_a_finished_sentence():
    said = []
    speech = TurnSpeech("kokoro/ef_dora", lambda text, voice: said.append((text, voice)))
    speech.feed("Voy a ello.")
    assert said == []
    speech.flush()
    assert said == [("Voy a ello.", "kokoro/ef_dora")]
    speech.feed(" Hecho.")
    speech.finish()
    assert said[-1] == ("Hecho.", "kokoro/ef_dora")
