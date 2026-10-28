"""PartialJsonFieldExtractor: incremental speech_text/display_text from partial JSON
(specs/front-agent)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tony.core.runner.partial_json import PartialJsonFieldExtractor

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "front"
STREAM = FIXTURES / "structured_output_stream.json"
GOLDEN = FIXTURES / "structured_output_emissions.json"


def run(chunks: list[str]) -> tuple[list[tuple[str, str]], PartialJsonFieldExtractor]:
    extractor = PartialJsonFieldExtractor()
    emitted: list[tuple[str, str]] = []
    for chunk in chunks:
        emitted += extractor.feed(chunk)
    return emitted, extractor


def joined(emitted: list[tuple[str, str]]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for field, text in emitted:
        fields[field] = fields.get(field, "") + text
    return fields


def one_char_chunks(text: str) -> list[str]:
    return list(text)


DOCUMENTS = [
    {"speech_text": "Son las diez.", "display_text": "Son las **10**."},
    {"display_text": "Primero display.", "speech_text": "Luego habla."},
    {"speech_text": None, "display_text": "Solo texto."},
    {"speech_text": 'Dijo "hola" \\ y\nadiós, señor á', "display_text": "Tab\tóñ €"},
    {"x": {"a": [1, "}", {"b": '"]'}]}, "speech_text": "Tras anidados.", "y": [True, None, 2.5]},
    {"speech_text": "Emoji 😀 fin.", "display_text": ""},
]


@pytest.mark.parametrize("document", DOCUMENTS)
@pytest.mark.parametrize("indent", [None, 2])
def test_one_char_chunks_and_whole_json_give_the_same_fields(document: dict, indent) -> None:
    text = json.dumps(document, ensure_ascii=False, indent=indent)
    expected = {k: v for k, v in document.items() if k in ("speech_text", "display_text") and v}

    by_char, char_extractor = run(one_char_chunks(text))
    whole, whole_extractor = run([text])

    assert joined(by_char) == expected
    assert joined(whole) == expected
    assert not char_extractor.broken and not whole_extractor.broken


def test_ascii_escapes_are_decoded_too() -> None:
    text = json.dumps({"speech_text": "señor ¿ü€😀"}, ensure_ascii=True)

    assert joined(run(one_char_chunks(text))[0]) == {"speech_text": "señor ¿ü€😀"}


def test_fields_are_emitted_in_stream_order_one_fragment_per_feed() -> None:
    emitted, _ = run(
        ['{"speech_text": "Son las', ' diez.", "display_text": "Son las **10**', '."}']
    )

    assert emitted == [
        ("speech_text", "Son las"),
        ("speech_text", " diez."),
        ("display_text", "Son las **10**"),
        ("display_text", "."),
    ]


def test_a_split_escape_is_decoded_without_backslashes() -> None:
    emitted, _ = run(['{"speech_text": "dijo \\', '"hola\\"', ' ya"}'])

    assert joined(emitted) == {"speech_text": 'dijo "hola" ya'}


def test_a_unicode_escape_split_in_three_chunks() -> None:
    emitted, _ = run(['{"speech_text": "Se\\u0', "0f", '1or"}'])

    assert emitted == [("speech_text", "Se"), ("speech_text", "ñor")]


def test_nothing_is_emitted_for_an_empty_feed_or_before_a_string_starts() -> None:
    emitted, _ = run(["", '{"speech_text"', ": ", '"'])

    assert emitted == []


@pytest.mark.parametrize(
    "chunks",
    [
        ['{"speech_text": 5'],
        ['{"speech_text": "a", "display_text": {"x": 1}}'],
        ["[1, 2]"],
        ['{"speech_text" "a"}'],
        ['{"speech_text": "a" "b"}'],
        ['{speech_text: "a"}'],
        ['{"speech_text": "a"} x'],
        ['{"speech_text": "\\q"}'],
        ['{"speech_text": "\\u12G4"}'],
        ['{"speech_text": "Hola', '", "display_text": nux'],
    ],
)
def test_broken_json_stops_emitting_without_raising(chunks: list[str]) -> None:
    extractor = PartialJsonFieldExtractor()
    for chunk in chunks:
        extractor.feed(chunk)

    assert extractor.broken
    assert extractor.feed('"speech_text": "más"}') == []


def test_emissions_before_breaking_are_kept() -> None:
    extractor = PartialJsonFieldExtractor()

    first = extractor.feed('{"speech_text": "Hola", "display_text": 5')

    assert first == [("speech_text", "Hola")]
    assert extractor.broken


def test_null_display_text_and_whitespace_only_documents_are_accepted() -> None:
    emitted, extractor = run(["  \n{ ", ' "display_text" : null , "speech_text":"x" } \n'])

    assert emitted == [("speech_text", "x")]
    assert not extractor.broken


def recorded_chunks() -> tuple[list[str], dict]:
    recording = json.loads(STREAM.read_text(encoding="utf-8"))
    chunks = [
        event["delta"]["partial_json"]
        for event in recording["events"]
        if event["type"] == "content_block_delta"
    ]
    return chunks, recording["structured_output"]


def test_golden_emissions_of_the_recorded_stream() -> None:
    chunks, final = recorded_chunks()

    emitted, extractor = run(chunks)

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(emitted, ensure_ascii=False, indent=1) + "\n", "utf-8")
    assert [tuple(item) for item in json.loads(GOLDEN.read_text(encoding="utf-8"))] == emitted
    assert joined(emitted) == final
    assert not extractor.broken
