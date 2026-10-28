"""Incremental segmentation of spoken text, tolerant to abbreviations and decimals.

Pieces are sentences; in `first_clause` mode the first piece of a reply is cut short (first
clause or six words) so synthesis can start before the first sentence is complete. Each
piece carries the kind of cut that ended it, so the pipeline can pause accordingly.
"""

from __future__ import annotations

import re
from typing import Literal

ABBREVIATIONS = frozenset(
    {"sr.", "sra.", "dr.", "dra.", "ud.", "uds.", "núm.", "etc.", "p. ej.", "ej.", "pág."}
)
BIGRAM_ABBREVIATIONS = tuple(a.split(" ", 1) for a in ABBREVIATIONS if " " in a)
# A terminal mark closes a sentence only once the next sentence has visibly started, so a
# fragment that ends in `10.` can still turn out to be the decimal `10.5`.
BOUNDARY = re.compile(r"(?P<mark>[.?!…;])(?=\s+\S)|(?P<paragraph>\n[ \t]*\n)")
# A word counts once whitespace follows it, so a streamed `10,` can still become `10,5`.
COMPLETE_WORD = re.compile(r"\S+(?=\s)")
CLAUSE_MARKS = frozenset(",:;")
FIRST_CLAUSE_WORDS = 6

CutKind = Literal["clause", "sentence", "final"]


class Piece(str):
    """A piece of text to speak, tagged with the kind of cut that ended it."""

    kind: CutKind

    def __new__(cls, text: str, kind: CutKind) -> Piece:
        piece = super().__new__(cls, text)
        piece.kind = kind
        return piece


def split_sentences(text: str) -> list[str]:
    segmenter = SentenceSegmenter()
    sentences = segmenter.feed(text)
    rest = segmenter.flush()
    return sentences if rest is None else [*sentences, rest]


class SentenceSegmenter:
    def __init__(self, first_clause: bool = False) -> None:
        self._buffer = ""
        self._first_clause = first_clause
        self._emitted = False

    def feed(self, text: str) -> list[Piece]:
        self._buffer += text
        pieces: list[Piece] = []
        while (cut := self._next_cut()) is not None:
            end, resume, kind = cut
            piece = self._buffer[:end].strip()
            self._buffer = self._buffer[resume:]
            if piece:
                pieces.append(Piece(piece, kind))
                self._emitted = True
        return pieces

    def flush(self) -> Piece | None:
        rest, self._buffer = self._buffer.strip(), ""
        return Piece(rest, "final") if rest else None

    def _next_cut(self) -> tuple[int, int, CutKind] | None:
        sentence = self._sentence_cut()
        clause = self._clause_cut() if self._first_clause and not self._emitted else None
        if clause is not None and (sentence is None or clause < sentence[0]):
            return clause, clause, "clause"
        if sentence is not None:
            return sentence[0], sentence[1], "sentence"
        return None

    def _sentence_cut(self) -> tuple[int, int] | None:
        for match in BOUNDARY.finditer(self._buffer):
            if match.group("paragraph") is not None:
                return match.start(), match.end()
            if match.group("mark") == "." and self._is_abbreviation(match.start()):
                continue
            return match.end(), match.end()
        return None

    def _clause_cut(self) -> int | None:
        for position, word in enumerate(COMPLETE_WORD.finditer(self._buffer), start=1):
            if word.group()[-1] in CLAUSE_MARKS or position == FIRST_CLAUSE_WORDS:
                return word.end()
        return None

    def _is_abbreviation(self, dot: int) -> bool:
        word = self._buffer[: dot + 1].split()[-1].lower()
        if word in ABBREVIATIONS:
            return True
        following = self._buffer[dot + 1 :].lstrip().lower()
        return any(
            word == first and following.startswith(second) for first, second in BIGRAM_ABBREVIATIONS
        )
