"""speech_text_for: what gets spoken when the front gives no speech_text (specs/voice-output)."""

from __future__ import annotations

import pytest

from tony.core.logging.redact import MASK
from tony.core.voice.cleanup import (
    MAX_SPEECH_CHARS,
    SCREEN_SUFFIX,
    SpeechText,
    speech_text_for,
    strip_markdown,
)

CODE = "Usa **uv**:\n```bash\nuv sync\n```\nListo."


def test_speech_text_present_is_used_verbatim() -> None:
    result = speech_text_for("| a | b |", "Te lo muestro.")

    assert result == SpeechText("Te lo muestro.", truncated=False, stripped=False)


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_empty_speech_text_counts_as_absent(missing: str | None) -> None:
    assert speech_text_for("Son las diez.", missing).text == "Son las diez."


@pytest.mark.parametrize(
    ("display_text", "spoken"),
    [
        ("Aquí tiene la tabla:\n|a|b|\n|1|2|", f"Aquí tiene la tabla: {SCREEN_SUFFIX}"),
        (CODE, f"Usa uv: Listo. {SCREEN_SUFFIX}"),
        ("Mira: ![img](u)", f"Mira: {SCREEN_SUFFIX}"),
        ("Lee ~~~\nx = 1\n~~~ ya.", f"Lee ya. {SCREEN_SUFFIX}"),
    ],
)
def test_removed_blocks_add_the_screen_suffix(display_text: str, spoken: str) -> None:
    result = speech_text_for(display_text, None)

    assert result.text == spoken
    assert result.stripped is True and result.truncated is False


@pytest.mark.parametrize(
    ("display_text", "spoken"),
    [
        ("[docs](https://x)", "docs"),
        ("# Título\n- uno\n- dos", "Título uno dos"),
        ("1. uno\n2) dos\n* tres\n+ cuatro", "uno dos tres cuatro"),
        ("> cita _suave_ y `código` __fuerte__", "cita suave y código fuerte"),
        ("Son las diez.", "Son las diez."),
        ("Ve a https://example.com/a_b ahora", "Ve a https://example.com/a_b ahora"),
    ],
)
def test_inline_markdown_is_flattened_without_suffix(display_text: str, spoken: str) -> None:
    result = speech_text_for(display_text, None)

    assert result.text == spoken
    assert result.stripped is False and result.truncated is False


def test_long_prose_is_cut_at_a_word_boundary_and_suffixed() -> None:
    prose = " ".join(f"palabra{i}" for i in range(120))
    assert len(prose) > 900

    result = speech_text_for(prose, None)

    spoken = result.text.removesuffix(f" {SCREEN_SUFFIX}")
    head = prose[:MAX_SPEECH_CHARS]
    assert result.truncated is True and result.stripped is False
    assert spoken == head[: head.rfind(" ")]
    assert len(spoken) > MAX_SPEECH_CHARS - 12


def test_only_a_removed_block_speaks_the_suffix_alone() -> None:
    assert speech_text_for("![img](u)", None).text == SCREEN_SUFFIX


def test_exactly_max_chars_is_not_truncated() -> None:
    prose = "a" * MAX_SPEECH_CHARS

    assert speech_text_for(prose, None) == SpeechText(prose, truncated=False, stripped=False)


def test_a_redaction_mask_is_spoken_as_a_hidden_datum_not_as_asterisks() -> None:
    assert speech_text_for(f"La clave es {MASK}.", None).text == "La clave es dato oculto."
    assert speech_text_for("x", f"Clave {MASK}").text == "Clave dato oculto"


def test_strip_markdown_reports_whether_a_block_was_removed() -> None:
    assert strip_markdown("solo *texto*") == ("solo texto", False)
    assert strip_markdown("x\n|a|\ny") == ("x y", True)
