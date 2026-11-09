import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.memory.history import HISTORY_FILE, HistoryStore, StoredMessage, fit_history

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


def msgs(*sizes):
    return [StoredMessage("user", "jarvis", chr(97 + n) * size) for n, size in enumerate(sizes)]


def test_fit_history_under_budget_is_unchanged():
    messages = msgs(3, 4)

    assert fit_history(messages, 10) == messages


def test_fit_history_exactly_at_budget_is_unchanged():
    messages = msgs(3, 4)

    assert fit_history(messages, 7) == messages


def test_fit_history_drops_oldest_first_and_keeps_order():
    messages = msgs(5, 4, 3)

    assert fit_history(messages, 7) == messages[1:]
    assert fit_history(messages, 6) == messages[2:]


def test_fit_history_keeps_a_suffix_not_a_subset():
    messages = msgs(2, 9, 2)

    assert fit_history(messages, 5) == messages[2:]


def test_fit_history_cuts_a_single_huge_message_to_the_budget():
    [only] = msgs(50)

    [fitted] = fit_history([only], 10)

    assert fitted.content == "a" * 7 + "[…]"
    assert (fitted.role, fitted.agent) == (only.role, only.agent)


def test_fit_history_cuts_the_newest_when_it_alone_exceeds_the_budget():
    older, newest = msgs(2, 50)

    assert [m.content for m in fit_history([older, newest], 10)] == ["b" * 7 + "[…]"]


def test_fit_history_zero_disables():
    messages = msgs(500, 500)

    assert fit_history(messages, 0) == messages


def test_fit_history_empty_input():
    assert fit_history([], 10) == []


def test_fit_history_budget_smaller_than_the_marker_keeps_only_the_marker():
    [only] = msgs(50)

    assert [m.content for m in fit_history([only], 1)] == ["[…]"]
