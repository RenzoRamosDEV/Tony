"""Incremental extraction of top-level string fields from a JSON object that arrives in pieces.

The front streams its structured reply as `partial_json` fragments; this follows the lexical
state of the top-level object (key or value, inside a string, pending escape, a `\\uXXXX`
split across fragments, nested values of other keys) and returns the newly decoded text of the
tracked fields. Any invalid input marks it `broken` and it stops emitting: the final, complete
reply stays authoritative.
"""

from __future__ import annotations

from enum import Enum, auto

TRACKED_FIELDS = ("speech_text", "display_text")
SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
WHITESPACE = frozenset(" \t\n\r")
LITERAL_CHARS = frozenset("truefalsn0123456789+-.eE")
NULL = "null"
HIGH_SURROGATES = range(0xD800, 0xDC00)


class _State(Enum):
    START = auto()
    KEY_OR_END = auto()
    KEY = auto()
    COLON = auto()
    VALUE = auto()
    STRING = auto()
    NESTED = auto()
    LITERAL = auto()
    AFTER_VALUE = auto()
    DONE = auto()
    BROKEN = auto()


class PartialJsonFieldExtractor:
    def __init__(self, fields: tuple[str, ...] = TRACKED_FIELDS) -> None:
        self._fields = fields
        self._state = _State.START
        self._key = ""
        self._literal = ""
        self._nested_depth = 0
        self._nested_in_string = False
        self._nested_escape = False
        self._escape: str | None = None
        self._high_surrogate: int | None = None
        self._emitted: list[tuple[str, str]] = []

    @property
    def broken(self) -> bool:
        return self._state is _State.BROKEN

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """Decoded text of the tracked fields found in `chunk`, one entry per field run."""
        self._emitted = []
        for char in chunk:
            if self._state is _State.BROKEN:
                break
            self._step(char)
        return self._emitted

    def _step(self, char: str) -> None:
        handler = getattr(self, f"_on_{self._state.name.lower()}")
        if not handler(char):
            self._state = _State.BROKEN

    def _on_start(self, char: str) -> bool:
        if char == "{":
            self._state = _State.KEY_OR_END
        return char == "{" or char in WHITESPACE

    def _on_key_or_end(self, char: str) -> bool:
        if char == '"':
            self._key, self._state = "", _State.KEY
        elif char == "}":
            self._state = _State.DONE
        return char in '"}' or char in WHITESPACE

    def _on_key(self, char: str) -> bool:
        if self._escape is not None or char == "\\":
            self._escape = (self._escape or "") + char
            return self._escape_complete_or_pending(into_key=True)
        if char == '"':
            self._state = _State.COLON
        else:
            self._key += char
        return True

    def _on_colon(self, char: str) -> bool:
        if char == ":":
            self._state = _State.VALUE
        return char == ":" or char in WHITESPACE

    def _on_value(self, char: str) -> bool:
        if char in WHITESPACE:
            return True
        tracked = self._key in self._fields
        if char == '"':
            self._state = _State.STRING
        elif char in "{[" and not tracked:
            self._nested_depth, self._state = 1, _State.NESTED
        elif char in LITERAL_CHARS and (not tracked or char == "n"):
            self._literal, self._state = char, _State.LITERAL
        else:
            return False
        return True

    def _on_string(self, char: str) -> bool:
        if self._escape is not None or char == "\\":
            self._escape = (self._escape or "") + char
            return self._escape_complete_or_pending(into_key=False)
        if char == '"':
            self._state = _State.AFTER_VALUE
        else:
            self._emit(char)
        return True

    def _on_nested(self, char: str) -> bool:
        if self._nested_in_string:
            if self._nested_escape:
                self._nested_escape = False
            elif char == "\\":
                self._nested_escape = True
            elif char == '"':
                self._nested_in_string = False
        elif char == '"':
            self._nested_in_string = True
        elif char in "{[":
            self._nested_depth += 1
        elif char in "}]":
            self._nested_depth -= 1
            if self._nested_depth == 0:
                self._state = _State.AFTER_VALUE
        return True

    def _on_literal(self, char: str) -> bool:
        if char in LITERAL_CHARS:
            self._literal += char
            tracked = self._key in self._fields
            return not tracked or NULL.startswith(self._literal)
        if self._key in self._fields and self._literal != NULL:
            return False
        self._state = _State.AFTER_VALUE
        return self._on_after_value(char)

    def _on_after_value(self, char: str) -> bool:
        if char == ",":
            self._state = _State.KEY_OR_END
        elif char == "}":
            self._state = _State.DONE
        return char in ",}" or char in WHITESPACE

    def _on_done(self, char: str) -> bool:
        return char in WHITESPACE

    def _escape_complete_or_pending(self, into_key: bool) -> bool:
        """Decode `self._escape` (starting with a backslash) once it is complete."""
        escape = self._escape or ""
        if len(escape) < 2:
            return True
        kind = escape[1]
        if kind in SIMPLE_ESCAPES:
            self._escape = None
            self._append(SIMPLE_ESCAPES[kind], into_key)
            return True
        if kind != "u" or not all(c in HEX_DIGITS for c in escape[2:]):
            return False
        if len(escape) < 6:
            return True
        self._escape = None
        self._append_code_unit(int(escape[2:], 16), into_key)
        return True

    def _append_code_unit(self, code: int, into_key: bool) -> None:
        if code in HIGH_SURROGATES:
            self._high_surrogate = code
            return
        if self._high_surrogate is not None:
            high, self._high_surrogate = self._high_surrogate, None
            code = 0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00)
        self._append(chr(code), into_key)

    def _append(self, text: str, into_key: bool) -> None:
        if into_key:
            self._key += text
        else:
            self._emit(text)

    def _emit(self, text: str) -> None:
        if self._key not in self._fields:
            return
        if self._emitted and self._emitted[-1][0] == self._key:
            self._emitted[-1] = (self._key, self._emitted[-1][1] + text)
        else:
            self._emitted.append((self._key, text))
