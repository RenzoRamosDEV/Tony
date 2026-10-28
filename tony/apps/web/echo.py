"""Echo filter: a barge-in whose transcript repeats what Tony was saying is Tony hearing himself."""

from __future__ import annotations

import re
import unicodedata

MIN_ECHO_WORDS = 3
NON_WORD = re.compile(r"[^\w]+")


def normalize(text: str) -> str:
    """Lowercase words without accents or punctuation, single-spaced."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(NON_WORD.sub(" ", plain).split())


def is_echo(transcript: str, spoken: str) -> bool:
    heard = normalize(transcript)
    if len(heard.split()) < MIN_ECHO_WORDS:
        return False
    return f" {heard} " in f" {normalize(spoken)} "
