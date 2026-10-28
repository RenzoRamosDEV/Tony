"""ConversationStore: schema, history and task records in a temporary SQLite file."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tony.core.memory.conversations import ConversationStore
from tony.core.runner import TaskRequest, TaskResult


def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "memory" / "conversations.sqlite")


def columns(path: Path, table: str) -> list[str]:
    with sqlite3.connect(path) as connection:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def test_schema_is_created_on_open(tmp_path: Path) -> None:
    s = store(tmp_path)

    assert columns(s.path, "conversations") == ["id", "channel", "created_at", "sdk_session_id"]
    assert columns(s.path, "messages") == [
        "id",
        "conversation_id",
        "role",
        "content",
        "reply_mode",
        "created_at",
    ]
    assert columns(s.path, "tasks") == [
        "id",
        "conversation_id",
        "status",
        "request_json",
        "result_json",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "created_at",
        "finished_at",
    ]
    s.close()


def test_reopening_keeps_conversations_and_messages(tmp_path: Path) -> None:
    first = store(tmp_path)
    conversation = first.start_conversation("cli")
    first.add_message(conversation, "user", "hola", None)
    first.add_message(conversation, "assistant", "Hola, señor.", "text")
    first.close()

    second = store(tmp_path)

    assert second.last_conversation("cli") == conversation
    assert [(m.role, m.content, m.reply_mode) for m in second.recent_messages(conversation)] == [
        ("user", "hola", None),
        ("assistant", "Hola, señor.", "text"),
    ]
    second.close()


def test_recent_messages_returns_the_last_forty_in_ascending_order(tmp_path: Path) -> None:
    s = store(tmp_path)
    conversation = s.start_conversation("cli")
    for i in range(45):
        s.add_message(conversation, "user", f"m{i}", None)

    messages = s.recent_messages(conversation)

    assert len(messages) == 40
    assert messages[0].content == "m5"
    assert messages[-1].content == "m44"
    assert s.recent_messages(conversation, limit=2)[0].content == "m43"
    s.close()


def test_record_task_keeps_tokens_cost_and_json(tmp_path: Path) -> None:
    s = store(tmp_path)
    conversation = s.start_conversation("cli")
    request = TaskRequest(objetivo="lista")
    result = TaskResult(status="ok", resumen="3 ficheros", datos=["a.md"])

    s.record_task(
        "t1",
        conversation,
        status="done",
        request=request,
        result=result,
        tokens_in=120,
        tokens_out=40,
        cost_usd=0.003,
    )

    with sqlite3.connect(s.path) as connection:
        row = connection.execute(
            "SELECT id, conversation_id, status, request_json, result_json, tokens_in, "
            "tokens_out, cost_usd, created_at, finished_at FROM tasks"
        ).fetchone()
    assert row[:3] == ("t1", conversation, "done")
    assert json.loads(row[3]) == request.model_dump()
    assert json.loads(row[4]) == result.model_dump()
    assert row[5:8] == (120, 40, 0.003)
    assert row[8] is not None and row[9] is not None
    s.close()


def test_last_conversation_is_per_channel(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.start_conversation("cli")
    newest_cli = s.start_conversation("cli")
    s.start_conversation("web")

    assert s.last_conversation("cli") == newest_cli
    assert s.last_conversation("voice") is None
    s.close()


def test_ids_are_unique_hex(tmp_path: Path) -> None:
    s = store(tmp_path)

    ids = {s.start_conversation("cli") for _ in range(3)}

    assert len(ids) == 3
    assert all(len(i) == 32 for i in ids)
    s.close()


def test_sdk_session_id_round_trips_and_defaults_to_none(tmp_path: Path) -> None:
    s = store(tmp_path)
    conversation = s.start_conversation("cli")

    assert s.sdk_session(conversation) is None
    s.set_sdk_session(conversation, "sdk-1")
    assert s.sdk_session(conversation) == "sdk-1"
    s.set_sdk_session(conversation, "sdk-2")
    assert s.sdk_session(conversation) == "sdk-2"
    assert s.sdk_session("missing") is None
    s.close()


def test_database_created_before_the_sdk_session_column_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "memory" / "conversations.sqlite"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, channel TEXT NOT NULL,"
            " created_at TEXT NOT NULL);"
            "INSERT INTO conversations VALUES ('old', 'cli', '2026-01-01T00:00:00.000Z');"
        )

    s = ConversationStore(path)
    s.set_sdk_session("old", "sdk-1")

    assert s.sdk_session("old") == "sdk-1"
    assert s.last_conversation("cli") == "old"
    s.close()


# --- ids, full history and listing (specs/user-memory, change 04) ------------------------------


def test_add_message_returns_the_id_that_messages_exposes(tmp_path: Path) -> None:
    s = store(tmp_path)
    conversation = s.start_conversation("web")

    generated = s.add_message(conversation, "user", "hola", None)
    explicit = s.add_message(conversation, "assistant", "Hola.", "text", message_id="m1")

    messages = s.messages(conversation)
    assert [(m.id, m.role, m.content, m.reply_mode) for m in messages] == [
        (generated, "user", "hola", None),
        ("m1", "assistant", "Hola.", "text"),
    ]
    assert explicit == "m1"
    assert len(generated) == 32
    assert all(m.created_at for m in messages)
    assert s.recent_messages(conversation)[0].id == generated
    s.close()


def test_messages_of_an_empty_or_unknown_conversation_is_an_empty_list(tmp_path: Path) -> None:
    s = store(tmp_path)
    conversation = s.start_conversation("web")

    assert s.messages(conversation) == []
    assert s.messages("nope") == []
    s.close()


def test_list_conversations_returns_the_twenty_most_recent_first(tmp_path: Path) -> None:
    s = store(tmp_path)
    created = [s.start_conversation("cli" if i % 5 == 0 else "web") for i in range(25)]

    listed = s.list_conversations()

    assert len(listed) == 20
    assert [c.id for c in listed] == list(reversed(created))[:20]
    assert listed[0].channel == "web" and listed[4].channel == "cli"
    assert all(c.created_at for c in listed)
    assert [c.id for c in s.list_conversations(limit=2)] == [created[24], created[23]]
    s.close()


def test_has_conversation(tmp_path: Path) -> None:
    s = store(tmp_path)
    conversation = s.start_conversation("cli")

    assert s.has_conversation(conversation) is True
    assert s.has_conversation("nope") is False
    s.close()
