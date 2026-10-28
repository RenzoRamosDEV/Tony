"""Reply mode resolution and the front's output contract (specs/reply-mode)."""

from __future__ import annotations

import pytest

from tony.core.loader import Style
from tony.core.runner.reply_mode import (
    EffectiveMode,
    FrontReply,
    parse_front_reply,
    resolve_reply_mode,
    strip_prefix,
    style_instruction,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/v ¿qué tiempo hace?", ("voice", "¿qué tiempo hace?")),
        ("/t hola", ("text", "hola")),
        ("/b   hola  ", ("both", "hola")),
        ("hola", (None, "hola")),
        ("/t", ("text", "")),
        ("/v\n", ("voice", "")),
        ("/tx hola", (None, "/tx hola")),
        ("/mode voice", (None, "/mode voice")),
        ("", (None, "")),
    ],
)
def test_strip_prefix(text: str, expected: tuple[str | None, str]) -> None:
    assert strip_prefix(text) == expected


@pytest.mark.parametrize(
    ("prefix", "persisted", "yaml", "modality", "expected"),
    [
        ("voice", "text", "auto", "text", EffectiveMode("voice", "prefix")),
        (None, "text", "voice", "audio", EffectiveMode("text", "settings")),
        (None, None, "both", "text", EffectiveMode("both", "yaml")),
        (None, None, "auto", "text", EffectiveMode("text", "yaml")),
        (None, None, "auto", "audio", EffectiveMode("voice", "yaml")),
        (None, "auto", "text", "audio", EffectiveMode("voice", "settings")),
        (None, "auto", "voice", "text", EffectiveMode("text", "settings")),
        ("both", "voice", "voice", "audio", EffectiveMode("both", "prefix")),
    ],
)
def test_precedence_prefix_over_settings_over_yaml(
    prefix, persisted, yaml, modality, expected
) -> None:
    assert resolve_reply_mode(prefix, persisted, yaml, modality) == expected


STYLE = Style(voice="Frases cortas", text="Markdown completo")


def test_voice_style_only_for_voice() -> None:
    instruction = style_instruction(STYLE, "voice")

    assert "Frases cortas" in instruction
    assert "Markdown completo" not in instruction


def test_text_style_only_for_text() -> None:
    instruction = style_instruction(STYLE, "text")

    assert "Markdown completo" in instruction
    assert "Frases cortas" not in instruction


def test_both_includes_both_styles_and_asks_for_two_versions() -> None:
    instruction = style_instruction(STYLE, "both")

    assert "Frases cortas" in instruction
    assert "Markdown completo" in instruction
    assert "speech_text" in instruction and "display_text" in instruction


def test_empty_style_gives_a_neutral_instruction() -> None:
    assert style_instruction(Style(), "text") == "Estilo: (sin indicaciones)"


def test_valid_structured_output_in_voice_is_kept_verbatim() -> None:
    reply = parse_front_reply(
        {"display_text": "| a | b |\n|---|---|", "speech_text": "Dos columnas, a y b"},
        fallback_text="x",
        mode="voice",
    )

    assert reply == FrontReply(
        display_text="| a | b |\n|---|---|", speech_text="Dos columnas, a y b"
    )


def test_speech_text_is_forced_to_null_in_text_mode() -> None:
    reply = parse_front_reply(
        {"display_text": "Hola", "speech_text": "Hola"}, fallback_text="x", mode="text"
    )

    assert reply == FrontReply(display_text="Hola", speech_text=None)


@pytest.mark.parametrize("structured", [None, {"texto": "Hola"}, {"display_text": 3}, "Hola"])
def test_invalid_or_missing_structured_output_falls_back_to_plain_text(structured) -> None:
    reply = parse_front_reply(structured, fallback_text="Hola, señor.", mode="voice")

    assert reply == FrontReply(display_text="Hola, señor.", speech_text=None)


def test_front_reply_schema_has_both_fields() -> None:
    schema = FrontReply.model_json_schema()

    assert set(schema["properties"]) == {"display_text", "speech_text"}
    assert schema["required"] == ["display_text"]
