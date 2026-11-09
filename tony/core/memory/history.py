import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC
from pathlib import Path
from typing import Literal

from tony.core.config.placeholders import SecretMasker
from tony.core.logging.task_log import Clock, utc_now

HISTORY_FILE = "memory/conversations.sqlite"
HISTORY_WINDOW = 20
Role = Literal["user", "assistant"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    agent TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages (conversation_id, id);
"""


@dataclass(frozen=True)
class StoredMessage:
    role: Role
    agent: str
    content: str


CUT_MARKER = "[…]"


def fit_history(messages: list[StoredMessage], max_chars: int) -> list[StoredMessage]:
    """Newest suffix of messages within max_chars; an oversized newest one is cut. 0 disables."""
    if max_chars <= 0:
        return messages
    kept: list[StoredMessage] = []
    used = 0
    for message in reversed(messages):
        if used + len(message.content) > max_chars:
            break
        kept.append(message)
        used += len(message.content)
    if not kept and messages:
        newest = messages[-1]
        room = max(0, max_chars - len(CUT_MARKER))
        return [replace(newest, content=newest.content[:room] + CUT_MARKER)]
    return kept[::-1]


class HistoryStore:
    """Conversation messages in memory/conversations.sqlite; one connection, one thread."""

    def __init__(self, root: Path, masker: SecretMasker, *, clock: Clock = utc_now) -> None:
        path = root / HISTORY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.executescript(_SCHEMA)
        self._masker = masker
        self._clock = clock

    def add(self, conversation_id: str, role: Role, agent: str, content: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO messages (conversation_id, role, agent, content, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    role,
                    agent,
                    self._masker.mask(content),
                    self._clock().astimezone(UTC).isoformat(),
                ),
            )

    def recent(self, conversation_id: str, limit: int = HISTORY_WINDOW) -> list[StoredMessage]:
        newest_first = self._connection.execute(
            "SELECT role, agent, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [StoredMessage(*row) for row in reversed(newest_first)]

    def close(self) -> None:
        self._connection.close()
