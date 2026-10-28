"""SentenceSegmenter: boundaries, abbreviations, decimals, streaming (specs/voice-output)."""

from __future__ import annotations

import pytest

from tony.core.voice.segmenter import ABBREVIATIONS, SentenceSegmenter, split_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Son las 10:30, señor. Tiene 3 reuniones hoy. La primera, p. ej., a las 11.",
            ["Son las 10:30, señor.", "Tiene 3 reuniones hoy.", "La primera, p. ej., a las 11."],
        ),
        ("Cuesta 10.5 euros; es barato.", ["Cuesta 10.5 euros;", "es barato."]),
        ("El Dr. Pérez llega… ¿Le aviso?", ["El Dr. Pérez llega…", "¿Le aviso?"]),
        ("Hola\n\nAdiós", ["Hola", "Adiós"]),
        ("Buenos días señor", ["Buenos días señor"]),
        ("¡Claro! ¿Algo más?", ["¡Claro!", "¿Algo más?"]),
        ("Uno.  Dos.\nTres.", ["Uno.", "Dos.", "Tres."]),
        ("", []),
        ("   \n\n  ", []),
    ],
)
def test_sentence_table(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize("abbreviation", ["Sr.", "Sra.", "Dra.", "Ud.", "Uds.", "etc.", "núm."])
def test_abbreviations_do_not_cut(abbreviation: str) -> None:
    assert abbreviation.lower() in ABBREVIATIONS
    text = f"Llame al {abbreviation} García mañana. Gracias."

    assert split_sentences(text) == [f"Llame al {abbreviation} García mañana.", "Gracias."]


def test_a_dot_followed_by_the_second_half_of_a_bigram_still_cuts_after_a_normal_word() -> None:
    assert split_sentences("Fin. ej. nada") == ["Fin.", "ej. nada"]


def test_a_word_that_merely_ends_like_an_abbreviation_still_cuts() -> None:
    assert split_sentences("Es un tesoro. Ud. verá.") == ["Es un tesoro.", "Ud. verá."]


def test_incremental_feed_emits_complete_sentences_and_retains_the_rest() -> None:
    segmenter = SentenceSegmenter()

    assert segmenter.feed("Son las 10") == []
    assert segmenter.feed(":30, señor. Tiene") == ["Son las 10:30, señor."]
    assert segmenter.feed(" 3 reuniones") == []
    assert segmenter.flush() == "Tiene 3 reuniones"
    assert segmenter.flush() is None


def test_trailing_punctuation_waits_for_the_next_fragment_or_the_flush() -> None:
    segmenter = SentenceSegmenter()

    assert segmenter.feed("Cuesta 10.") == []
    assert segmenter.feed("5 euros. Vale") == ["Cuesta 10.5 euros."]
    assert segmenter.flush() == "Vale"


def test_bigram_abbreviation_split_across_fragments_does_not_cut() -> None:
    segmenter = SentenceSegmenter()

    assert segmenter.feed("Tome algo, p. ") == []
    assert segmenter.feed("ej. agua. Luego") == ["Tome algo, p. ej. agua."]
    assert segmenter.flush() == "Luego"
