"""What to speak when the front gives no speech_text: display_text without markdown, bounded."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tony.core.logging.redact import MASK

MAX_SPEECH_CHARS = 600
SCREEN_SUFFIX = "…te lo muestro en pantalla"
SPOKEN_MASK = "dato oculto"

FENCED_CODE = re.compile(r"(```|~~~).*?\1", re.DOTALL)
TABLE_LINE = re.compile(r"^[ \t]*\|.*$", re.MULTILINE)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
BLOCK_PATTERNS = (FENCED_CODE, TABLE_LINE, IMAGE)

HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
QUOTE = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
LIST_MARKER = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.MULTILINE)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
INLINE_CODE = re.compile(r"`([^`]*)`")
EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1")
WHITESPACE = re.compile(r"\s+")
INLINE_PATTERNS = (
    (HEADING, ""),
    (QUOTE, ""),
    (LIST_MARKER, ""),
    (LINK, r"\1"),
    (INLINE_CODE, r"\1"),
    (EMPHASIS, r"\2"),
)


@dataclass(frozen=True)
class SpeechText:
    text: str
    truncated: bool
    stripped: bool


def strip_markdown(text: str) -> tuple[str, bool]:
    """Plain prose of a markdown text and whether a block (code, table, image) was dropped."""
    stripped = False
    for pattern in BLOCK_PATTERNS:
        text, count = pattern.subn("", text)
        stripped = stripped or count > 0
    for pattern, replacement in INLINE_PATTERNS:
        text = pattern.sub(replacement, text)
    return WHITESPACE.sub(" ", text).strip(), stripped


def speech_text_for(display_text: str, speech_text: str | None) -> SpeechText:
    if speech_text is not None and speech_text.strip():
        return SpeechText(_spoken_mask(speech_text), truncated=False, stripped=False)
    text, stripped = strip_markdown(_spoken_mask(display_text))
    truncated = len(text) > MAX_SPEECH_CHARS
    if truncated:
        text = text[:MAX_SPEECH_CHARS].rsplit(" ", 1)[0]
    if truncated or stripped:
        text = f"{text} {SCREEN_SUFFIX}" if text else SCREEN_SUFFIX
    return SpeechText(text, truncated=truncated, stripped=stripped)


def _spoken_mask(text: str) -> str:
    return text.replace(MASK, SPOKEN_MASK)
