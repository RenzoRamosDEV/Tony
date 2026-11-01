import re
from collections.abc import Callable

from tony.core.voice.sentences import SentenceSplitter

SCREEN_PHRASE = "Te lo dejo en pantalla."
LONG_REPLY_CHARS = 600
IMMEDIATE_ITEMS = 2
FENCE = "```"
TABLE_ROW = "|"

_MARKUP = [
    (re.compile(r"^\s*#+\s*"), ""),
    (re.compile(r"^\s*(?:[-*+]|\d+[.)])(?:\s+|$)"), ""),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"\1"),
    (re.compile(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"), r"\1"),
    (re.compile(r"`+"), ""),
    (re.compile(r"\*\*|__"), ""),
]


def spoken_text(item: str) -> str:
    """Remove Markdown markup that must not be read aloud."""
    for pattern, replacement in _MARKUP:
        item = pattern.sub(replacement, item)
    return " ".join(item.split())


class SpokenFilter:
    """Replaces code blocks and tables by SCREEN_PHRASE (once per run) and strips markup."""

    def __init__(self) -> None:
        self._in_fence = False
        self._last_was_phrase = False

    def push(self, item: str) -> list[str]:
        stripped = item.lstrip()
        if self._in_fence:
            self._in_fence = not stripped.startswith(FENCE)
            return []
        if stripped.startswith(FENCE):
            self._in_fence = True
            return self._phrase()
        if stripped.startswith(TABLE_ROW):
            return self._phrase()
        text = spoken_text(item)
        if not text:
            return []
        self._last_was_phrase = False
        return [text]

    def _phrase(self) -> list[str]:
        if self._last_was_phrase:
            return []
        self._last_was_phrase = True
        return [SCREEN_PHRASE]


class LongReplyGate:
    """Speaks the first two items at once and holds the rest until the reply length is known:
    replies over LONG_REPLY_CHARS end with SCREEN_PHRASE instead of the held items."""

    def __init__(self) -> None:
        self._passed: list[str] = []
        self._held: list[str] = []

    def push(self, item: str) -> list[str]:
        if len(self._passed) < IMMEDIATE_ITEMS:
            self._passed.append(item)
            return [item]
        self._held.append(item)
        return []

    def finish(self, reply_chars: int) -> list[str]:
        held, self._held = self._held, []
        if reply_chars <= LONG_REPLY_CHARS:
            return held
        if self._passed and self._passed[-1] == SCREEN_PHRASE:
            return []
        return [SCREEN_PHRASE]


Say = Callable[[str, str], None]


class TurnSpeech:
    """The spoken stream of one reply: sentences, then the spoken filter, then the gate."""

    def __init__(self, voice: str, say: Say) -> None:
        self._voice = voice
        self._say = say
        self._splitter = SentenceSplitter()
        self._filter = SpokenFilter()
        self._gate = LongReplyGate()
        self._chars = 0

    def feed(self, chunk: str) -> None:
        self._chars += len(chunk)
        self._speak(self._splitter.feed(chunk))

    def flush(self) -> None:
        """Speak a buffered sentence that already ended, e.g. before a pause in the stream."""
        self._speak(self._splitter.flush_terminal())

    def finish(self) -> None:
        self._speak(self._splitter.finish())
        self._say_all(self._gate.finish(self._chars))

    def _speak(self, sentences: list[str]) -> None:
        for sentence in sentences:
            for item in self._filter.push(sentence):
                self._say_all(self._gate.push(item))

    def _say_all(self, items: list[str]) -> None:
        for item in items:
            self._say(item, self._voice)
