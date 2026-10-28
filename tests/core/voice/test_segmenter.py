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


def pieces_of(text: str, first_clause: bool = True) -> list[tuple[str, str]]:
    segmenter = SentenceSegmenter(first_clause=first_clause)
    pieces = segmenter.feed(text)
    rest = segmenter.flush()
    return [(p, p.kind) for p in [*pieces, *([rest] if rest is not None else [])]]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Buenas tardes, señor. Los sistemas están en línea.",
            [
                ("Buenas tardes,", "clause"),
                ("señor.", "sentence"),
                ("Los sistemas están en línea.", "final"),
            ],
        ),
        (
            "La reunión de las cinco con el equipo sigue en pie.",
            [("La reunión de las cinco con", "clause"), ("el equipo sigue en pie.", "final")],
        ),
        (
            "Cuesta 10,5 euros, señor.",
            [("Cuesta 10,5 euros,", "clause"), ("señor.", "final")],
        ),
        (
            "Uno dos tres cuatro cinco seis siete ocho nueve, diez.",
            [("Uno dos tres cuatro cinco seis", "clause"), ("siete ocho nueve, diez.", "final")],
        ),
        (
            "Uno dos tres cuatro cinco, seis siete.",
            [("Uno dos tres cuatro cinco,", "clause"), ("seis siete.", "final")],
        ),
        (
            "Sr. Pérez, le esperan. Ahora.",
            [("Sr. Pérez,", "clause"), ("le esperan.", "sentence"), ("Ahora.", "final")],
        ),
        ("Sí. Claro que sí, señor.", [("Sí.", "sentence"), ("Claro que sí, señor.", "final")]),
        ("Hora: las diez.", [("Hora:", "clause"), ("las diez.", "final")]),
        ("Hecho", [("Hecho", "final")]),
        ("", []),
    ],
)
def test_first_clause_mode_cuts_the_first_piece_short(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert pieces_of(text) == expected


def test_first_clause_streamed_word_by_word_gives_the_same_pieces() -> None:
    text = "La reunión de las cinco con el equipo sigue en pie. Buenas tardes, señor."
    segmenter = SentenceSegmenter(first_clause=True)
    pieces = []
    for word in text.split(" "):
        pieces += segmenter.feed(word + " ")
    pieces.append(segmenter.flush())

    assert pieces == [
        "La reunión de las cinco con",
        "el equipo sigue en pie.",
        "Buenas tardes, señor.",
    ]


def test_without_first_clause_pieces_are_sentences_then_final() -> None:
    assert pieces_of("Buenas tardes, señor. Los sistemas están en línea.", False) == [
        ("Buenas tardes, señor.", "sentence"),
        ("Los sistemas están en línea.", "final"),
    ]


def test_a_paragraph_break_is_a_sentence_cut() -> None:
    assert pieces_of("Hola\n\nAdiós", False) == [("Hola", "sentence"), ("Adiós", "final")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hora; las diez.", [("Hora;", "sentence"), ("las diez.", "final")]),
        (
            "Uno dos tres cuatro cinco seis\n\nSiete.",
            [("Uno dos tres cuatro cinco seis", "sentence"), ("Siete.", "final")],
        ),
    ],
)
def test_a_sentence_cut_at_the_same_place_as_the_clause_wins(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert pieces_of(text) == expected
