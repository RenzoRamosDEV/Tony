import re

_SENTENCE_END = re.compile(r"[.!?…]+(?=\s)|\n")
_TERMINAL = (".", "!", "?", "…")
_RAW_LINE_STARTS = ("|", "```")
_CLASSIFY_CHARS = 3


class SentenceSplitter:
    """Splits streamed reply text into sentences as soon as each one is complete.

    A sentence ends at `.`, `!`, `?` or `…` followed by whitespace, or at a line break, so
    `3.5` and `notas.md` stay whole. Table rows and code fences are kept as whole lines;
    a line is classified once its first three non-space characters (or its end) are known.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._raw_line: bool | None = None

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        sentences: list[str] = []
        while self._classify() and (piece := self._next_piece()) is not None:
            sentences.extend(piece)
        return sentences

    def flush_terminal(self) -> list[str]:
        """Release a buffered sentence that already ends in terminal punctuation."""
        if self._raw_line or not self._buffer.rstrip().endswith(_TERMINAL):
            return []
        if self._raw_line is None and self._buffer.lstrip().startswith(_RAW_LINE_STARTS):
            return []
        self._raw_line = False
        return self._take(len(self._buffer))

    def finish(self) -> list[str]:
        rest = self._take(len(self._buffer))
        self._raw_line = None
        return rest

    def _classify(self) -> bool:
        if self._raw_line is not None:
            return True
        line = self._buffer.split("\n", 1)[0]
        if "\n" not in self._buffer and len("".join(line.split())) < _CLASSIFY_CHARS:
            return False
        self._raw_line = line.lstrip().startswith(_RAW_LINE_STARTS)
        return True

    def _next_piece(self) -> list[str] | None:
        if self._raw_line:
            end = self._buffer.find("\n")
            return None if end < 0 else self._end_line(end)
        match = _SENTENCE_END.search(self._buffer)
        if match is None:
            return None
        if match.group() == "\n":
            return self._end_line(match.start())
        return self._take(match.end())

    def _end_line(self, end: int) -> list[str]:
        piece = self._take(end)
        self._buffer = self._buffer[1:]
        self._raw_line = None
        return piece

    def _take(self, end: int) -> list[str]:
        piece, self._buffer = self._buffer[:end].strip(), self._buffer[end:]
        return [piece] if piece else []
