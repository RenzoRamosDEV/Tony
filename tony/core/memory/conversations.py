"""Conversation history in SQLite: conversations, messages and delegated tasks."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from tony.core.logging import utc_timestamp
from tony.core.runner import TaskRequest, TaskResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sdk_session_id TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    reply_mode TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
"""
MIGRATIONS = {"conversations": {"sdk_session_id": "TEXT"}}
DEFAULT_RECENT = 40
DEFAULT_LISTED = 20
MESSAGE_COLUMNS = "id, role, content, reply_mode, created_at"


@dataclass(frozen=True)
class Message:
    id: str
    role: str
    content: str
    reply_mode: str | None
    created_at: str


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    channel: str
    created_at: str


class ConversationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(SCHEMA)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        for table, columns in MIGRATIONS.items():
            present = {row[1] for row in self._connection.execute(f"PRAGMA table_info({table})")}
            for column, kind in columns.items():
                if column not in present:
                    with self._connection:
                        self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    def start_conversation(self, channel: str) -> str:
        conversation_id = uuid.uuid4().hex
        with self._connection:
            self._connection.execute(
                "INSERT INTO conversations (id, channel, created_at) VALUES (?, ?, ?)",
                (conversation_id, channel, utc_timestamp()),
            )
        return conversation_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        reply_mode: str | None,
        message_id: str | None = None,
    ) -> str:
        message_id = message_id or uuid.uuid4().hex
        with self._connection:
            self._connection.execute(
                "INSERT INTO messages (id, conversation_id, role, content, reply_mode, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, reply_mode, utc_timestamp()),
            )
        return message_id

    def record_task(
        self,
        task_id: str,
        conversation_id: str,
        status: str,
        request: TaskRequest,
        result: TaskResult | None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        created_at: str | None = None,
    ) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO tasks (id, conversation_id, status, request_json,"
                " result_json, tokens_in, tokens_out, cost_usd, created_at, finished_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    conversation_id,
                    status,
                    request.model_dump_json(),
                    result.model_dump_json() if result is not None else None,
                    tokens_in,
                    tokens_out,
                    cost_usd,
                    created_at or utc_timestamp(),
                    utc_timestamp(),
                ),
            )

    def recent_messages(self, conversation_id: str, limit: int = DEFAULT_RECENT) -> list[Message]:
        rows = self._connection.execute(
            f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE conversation_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [_message(row) for row in reversed(rows)]

    def messages(self, conversation_id: str) -> list[Message]:
        rows = self._connection.execute(
            f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE conversation_id = ?"
            " ORDER BY created_at ASC, rowid ASC",
            (conversation_id,),
        ).fetchall()
        return [_message(row) for row in rows]

    def list_conversations(self, limit: int = DEFAULT_LISTED) -> list[ConversationSummary]:
        rows = self._connection.execute(
            "SELECT id, channel, created_at FROM conversations"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ConversationSummary(*row) for row in rows]

    def has_conversation(self, conversation_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row is not None

    def sdk_session(self, conversation_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT sdk_session_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row[0] if row else None

    def set_sdk_session(self, conversation_id: str, session_id: str) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE conversations SET sdk_session_id = ? WHERE id = ?",
                (session_id, conversation_id),
            )

    def last_conversation(self, channel: str) -> str | None:
        row = self._connection.execute(
            "SELECT id FROM conversations WHERE channel = ? ORDER BY created_at DESC, rowid DESC"
            " LIMIT 1",
            (channel,),
        ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self._connection.close()


def _message(row: tuple[str, str, str, str | None, str]) -> Message:
    return Message(*row)
