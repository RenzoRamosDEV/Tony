import pytest

from tony.core.voice.sentences import SentenceSplitter


def run(chunks):
    splitter = SentenceSplitter()
    out = [sentence for chunk in chunks for sentence in splitter.feed(chunk)]
    return out + splitter.finish()


def splits(text):
    """The whole text, every two-chunk split and one character at a time."""
    yield [text]
    for cut in range(1, len(text)):
        yield [text[:cut], text[cut:]]
    yield list(text)


CASES = [
    ("Buenas tardes, señor. Hace sol.", ["Buenas tardes, señor.", "Hace sol."]),
    ("Cuesta 3.5 euros.", ["Cuesta 3.5 euros."]),
    ("Abra notas.md ahora.", ["Abra notas.md ahora."]),
    ("¡Hola! ¿Qué tal?…", ["¡Hola!", "¿Qué tal?…"]),
    ("Opciones:\nla primera", ["Opciones:", "la primera"]),
    ("Uno.\n\n\nDos", ["Uno.", "Dos"]),
    ("Espere... ya está", ["Espere...", "ya está"]),
    ("A. b", ["A.", "b"]),
    ("sin final", ["sin final"]),
    ("", []),
    ("   \n  \n", []),
    ("| a. b | c. d |\n| 1 | 2 |", ["| a. b | c. d |", "| 1 | 2 |"]),
    ("```py\nx = 1. y\n```\nListo. Sí", ["```py", "x = 1.", "y", "```", "Listo.", "Sí"]),
    ("  | x. y |\nFin.", ["| x. y |", "Fin."]),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_sentences_for_every_chunk_split(text, expected):
    for chunks in splits(text):
        assert run(chunks) == expected, chunks


def test_first_sentence_is_emitted_before_the_next_word_arrives():
    splitter = SentenceSplitter()
    assert splitter.feed("Buenas tardes, señor.") == []
    assert splitter.feed(" ") == ["Buenas tardes, señor."]
    assert splitter.feed("Hace sol.") == []
    assert splitter.finish() == ["Hace sol."]


def test_finish_flushes_the_unterminated_rest_and_resets():
    splitter = SentenceSplitter()
    splitter.feed("Hola. Qué")
    assert splitter.finish() == ["Qué"]
    assert splitter.finish() == []
    assert run(["| a"]) == ["| a"]


@pytest.mark.parametrize(
    ("fed", "flushed", "rest"),
    [
        ("Buenas tardes, señor.", ["Buenas tardes, señor."], []),
        ("Voy a ello!", ["Voy a ello!"], []),
        ("Ya…", ["Ya…"], []),
        ("Cuesta 3", [], ["Cuesta 3"]),
        ("Hola, señor", [], ["Hola, señor"]),
        ("| a.", [], ["| a."]),
        ("```", [], ["```"]),
        ("", [], []),
    ],
)
def test_flush_terminal_releases_only_a_finished_sentence(fed, flushed, rest):
    splitter = SentenceSplitter()
    assert splitter.feed(fed) == []
    assert splitter.flush_terminal() == flushed
    assert splitter.finish() == rest


def test_text_after_a_flushed_sentence_continues_normally():
    splitter = SentenceSplitter()
    splitter.feed("Uno.")
    assert splitter.flush_terminal() == ["Uno."]
    assert splitter.feed(" Dos. Tres") == ["Dos."]
    assert splitter.finish() == ["Tres"]
