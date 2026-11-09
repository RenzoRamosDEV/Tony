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


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    title: str
    message_count: int
    last_ts: str


CUT_MARKER = "[…]"
TITLE_MAX_CHARS = 60
LIST_LIMIT = 20

_SUMMARIES = """
SELECT g.conversation_id,
       COALESCE((SELECT content FROM messages u
                 WHERE u.conversation_id = g.conversation_id AND u.role = 'user'
                 ORDER BY u.id LIMIT 1), ''),
       g.message_count,
       (SELECT ts FROM messages l WHERE l.id = g.last_id)
FROM (
    SELECT conversation_id, MAX(id) AS last_id, COUNT(*) AS message_count
    FROM messages
    {where}
    GROUP BY conversation_id
) g
ORDER BY g.last_id DESC
LIMIT ?
"""


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
        self._connection.create_function("contains_folded", 2, _contains_folded, deterministic=True)
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

    def list_conversations(self, limit: int = LIST_LIMIT) -> list[ConversationSummary]:
        return self._summaries("", (), limit)

    def search_conversations(self, text: str, limit: int = LIST_LIMIT) -> list[ConversationSummary]:
        if not text:
            return []
        where = (
            "WHERE conversation_id IN "
            "(SELECT conversation_id FROM messages WHERE contains_folded(content, ?))"
        )
        return self._summaries(where, (text,), limit)

    def has_conversation(self, conversation_id: str) -> bool:
        found = self._connection.execute(
            "SELECT 1 FROM messages WHERE conversation_id = ? LIMIT 1", (conversation_id,)
        ).fetchone()
        return found is not None

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connection:
            deleted = self._connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
        return deleted.rowcount > 0

    def _summaries(
        self, where: str, parameters: tuple[str, ...], limit: int
    ) -> list[ConversationSummary]:
        found = self._connection.execute(_SUMMARIES.format(where=where), (*parameters, limit))
        return [
            ConversationSummary(id, title[:TITLE_MAX_CHARS], count, last_ts)
            for id, title, count, last_ts in found.fetchall()
        ]

    def close(self) -> None:
        self._connection.close()


def _contains_folded(content: str, text: str) -> bool:
    return text.casefold() in content.casefold()
