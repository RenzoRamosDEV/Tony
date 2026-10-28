"""Echo filter of barge-in transcripts (specs/voice-input: Eco descartado)."""

from __future__ import annotations

import pytest

from tony.apps.web.echo import is_echo, normalize

SPOKEN = "Son las diez y media, señor. Tiene una reunión."


def test_normalize_drops_case_accents_and_punctuation() -> None:
    assert normalize("¡Señor, ¿QUÉ tal?  Reunión…") == "senor que tal reunion"


@pytest.mark.parametrize(
    ("heard", "echo"),
    [
        ("las diez y media", True),
        ("Las diez y media, señor.", True),
        ("media senor tiene", True),
        ("son las", False),
        ("las diez", False),
        ("para, ¿qué tiempo hace?", False),
        ("las diez y cuarto", False),
        ("diez y medi", False),
        ("", False),
    ],
)
def test_three_words_contained_in_what_tony_said_are_echo(heard: str, echo: bool) -> None:
    assert is_echo(heard, SPOKEN) is echo


def test_nothing_is_echo_when_tony_said_nothing() -> None:
    assert is_echo("las diez y media", "") is False
