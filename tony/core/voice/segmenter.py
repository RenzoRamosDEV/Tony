"""Incremental sentence segmentation of spoken text, tolerant to abbreviations and decimals."""

from __future__ import annotations

import re

ABBREVIATIONS = frozenset(
    {"sr.", "sra.", "dr.", "dra.", "ud.", "uds.", "núm.", "etc.", "p. ej.", "ej.", "pág."}
)
BIGRAM_ABBREVIATIONS = tuple(a.split(" ", 1) for a in ABBREVIATIONS if " " in a)
# A terminal mark closes a sentence only once the next sentence has visibly started, so a
# fragment that ends in `10.` can still turn out to be the decimal `10.5`.
BOUNDARY = re.compile(r"(?P<mark>[.?!…;])(?=\s+\S)|(?P<paragraph>\n[ \t]*\n)")


def split_sentences(text: str) -> list[str]:
    segmenter = SentenceSegmenter()
    sentences = segmenter.feed(text)
    rest = segmenter.flush()
    return sentences if rest is None else [*sentences, rest]


class SentenceSegmenter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences: list[str] = []
        while (cut := self._next_cut()) is not None:
            end, resume = cut
            sentence = self._buffer[:end].strip()
            self._buffer = self._buffer[resume:]
            if sentence:
                sentences.append(sentence)
        return sentences

    def flush(self) -> str | None:
        rest, self._buffer = self._buffer.strip(), ""
        return rest or None

    def _next_cut(self) -> tuple[int, int] | None:
        for match in BOUNDARY.finditer(self._buffer):
            if match.group("paragraph") is not None:
                return match.start(), match.end()
            if match.group("mark") == "." and self._is_abbreviation(match.start()):
                continue
            return match.end(), match.end()
        return None

    def _is_abbreviation(self, dot: int) -> bool:
        word = self._buffer[: dot + 1].split()[-1].lower()
        if word in ABBREVIATIONS:
            return True
        following = self._buffer[dot + 1 :].lstrip().lower()
        return any(
            word == first and following.startswith(second) for first, second in BIGRAM_ABBREVIATIONS
        )
