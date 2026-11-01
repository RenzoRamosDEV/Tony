import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.memory.history import HISTORY_FILE, HistoryStore, StoredMessage

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=timezone(timedelta(hours=1)))


@pytest.fixture
def store(tmp_path):
    history = HistoryStore(tmp_path, SecretMasker({"s3cr3t"}), clock=lambda: NOW)
    yield history
    history.close()


def rows(tmp_path):
    with sqlite3.connect(tmp_path / HISTORY_FILE) as connection:
        return connection.execute(
            "SELECT conversation_id, role, agent, content, ts FROM messages ORDER BY id"
        ).fetchall()


def test_creates_the_database_with_the_messages_table(tmp_path, store):
    with sqlite3.connect(tmp_path / HISTORY_FILE) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(messages)")]

    assert columns == ["id", "conversation_id", "role", "agent", "content", "ts"]


def test_add_stores_masked_content_and_utc_ts(tmp_path, store):
    store.add("c1", "user", "jarvis", "mi clave s3cr3t")
    store.add("c1", "assistant", "jarvis", "Buenas tardes, señor.")

    assert rows(tmp_path) == [
        ("c1", "user", "jarvis", "mi clave ***", "2026-11-01T09:00:00+00:00"),
        ("c1", "assistant", "jarvis", "Buenas tardes, señor.", "2026-11-01T09:00:00+00:00"),
    ]


@pytest.mark.parametrize(("stored", "expected"), [(0, 0), (19, 19), (20, 20), (21, 20), (25, 20)])
def test_recent_returns_at_most_20_oldest_first(store, stored, expected):
    for n in range(stored):
        store.add("c1", "user", "jarvis", f"m{n}")

    recent = store.recent("c1", 20)

    assert [message.content for message in recent] == [
        f"m{n}" for n in range(stored - expected, stored)
    ]


def test_recent_excludes_other_conversations(store):
    store.add("old", "user", "jarvis", "antes")
    store.add("c1", "assistant", "viernes", "ahora")

    assert store.recent("c1", 20) == [
        StoredMessage(role="assistant", agent="viernes", content="ahora")
    ]


def test_data_survives_reopening(tmp_path):
    first = HistoryStore(tmp_path, SecretMasker())
    first.add("c1", "user", "jarvis", "Hola")
    first.close()

    second = HistoryStore(tmp_path, SecretMasker())
    try:
        assert [message.content for message in second.recent("c1", 20)] == ["Hola"]
    finally:
        second.close()


def test_default_clock_is_utc(tmp_path):
    history = HistoryStore(tmp_path, SecretMasker())
    history.add("c1", "user", "jarvis", "x")
    history.close()

    ts = datetime.fromisoformat(rows(tmp_path)[0][4])
    assert ts.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - ts) < timedelta(minutes=1)
