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


class Ticking:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Ticking()


@pytest.fixture
def timed_store(tmp_path, clock):
    history = HistoryStore(tmp_path, SecretMasker({"s3cr3t"}), clock=clock)
    yield history
    history.close()


def test_list_conversations_empty_store(store):
    assert store.list_conversations() == []


def test_list_conversations_newest_first_with_title_count_and_last_ts(timed_store, clock):
    timed_store.add("a", "user", "jarvis", "x" * 70)
    timed_store.add("a", "assistant", "jarvis", "respuesta")
    clock.now = NOW + timedelta(minutes=5)
    timed_store.add("b", "user", "jarvis", "hola")

    listed = timed_store.list_conversations()

    assert [(c.id, c.title, c.message_count, c.last_ts) for c in listed] == [
        ("b", "hola", 1, "2026-11-01T09:05:00+00:00"),
        ("a", "x" * 60, 2, "2026-11-01T09:00:00+00:00"),
    ]


def test_list_orders_by_last_message_not_first(timed_store):
    timed_store.add("a", "user", "jarvis", "uno")
    timed_store.add("b", "user", "jarvis", "dos")
    timed_store.add("a", "assistant", "jarvis", "tres")

    assert [c.id for c in timed_store.list_conversations()] == ["a", "b"]


@pytest.mark.parametrize(("length", "expected"), [(59, 59), (60, 60), (61, 60)])
def test_list_title_is_cut_at_60_characters(store, length, expected):
    store.add("a", "user", "jarvis", "t" * length)

    assert store.list_conversations()[0].title == "t" * expected


def test_list_title_is_the_first_user_message_not_an_assistant_one(store):
    store.add("a", "assistant", "jarvis", "saludo")
    store.add("a", "user", "jarvis", "primera")
    store.add("a", "user", "jarvis", "segunda")

    assert store.list_conversations()[0].title == "primera"


def test_list_title_is_empty_without_user_message(store):
    store.add("a", "assistant", "jarvis", "solo")

    assert store.list_conversations()[0].title == ""


def test_list_title_is_masked(store):
    store.add("a", "user", "jarvis", "clave s3cr3t")

    assert store.list_conversations()[0].title == "clave ***"


@pytest.mark.parametrize(("stored", "expected"), [(19, 19), (20, 20), (21, 20), (25, 20)])
def test_list_default_limit_is_20(store, stored, expected):
    for n in range(stored):
        store.add(f"c{n}", "user", "jarvis", "m")

    listed = store.list_conversations()

    assert len(listed) == expected
    assert listed[0].id == f"c{stored - 1}"


def test_list_explicit_limit(store):
    for n in range(3):
        store.add(f"c{n}", "user", "jarvis", "m")

    assert [c.id for c in store.list_conversations(limit=2)] == ["c2", "c1"]


def test_search_folds_case_and_accents_and_returns_each_conversation_once(store):
    store.add("a", "user", "jarvis", "Compra de CAFÉ")
    store.add("a", "assistant", "jarvis", "el café está caro")
    store.add("b", "user", "jarvis", "otra cosa")

    found = store.search_conversations("café")

    assert [c.id for c in found] == ["a"]
    assert found[0].message_count == 2
    assert [c.id for c in store.search_conversations("CAFÉ")] == ["a"]


def test_search_folds_case_in_both_directions(store):
    store.add("upper", "user", "jarvis", "CAFÉ")
    store.add("lower", "user", "jarvis", "café")

    assert {c.id for c in store.search_conversations("café")} == {"upper", "lower"}
    assert {c.id for c in store.search_conversations("CAFÉ")} == {"upper", "lower"}


def test_search_counts_all_messages_of_a_matching_conversation(store):
    store.add("a", "user", "jarvis", "tema")
    store.add("a", "assistant", "jarvis", "otra cosa")

    assert store.search_conversations("tema")[0].message_count == 2


def test_search_is_a_substring_match(store):
    store.add("a", "user", "jarvis", "una cafetera")

    assert [c.id for c in store.search_conversations("fete")] == ["a"]


def test_search_does_not_equate_accented_and_plain_letters(store):
    store.add("a", "user", "jarvis", "cafe")

    assert store.search_conversations("café") == []


def test_search_matches_masked_content_only(store):
    store.add("a", "user", "jarvis", "mi clave s3cr3t")

    assert store.search_conversations("s3cr3t") == []
    assert [c.id for c in store.search_conversations("clave")] == ["a"]


def test_search_empty_text_returns_nothing(store):
    store.add("a", "user", "jarvis", "algo")

    assert store.search_conversations("") == []


def test_search_newest_first_and_limit_applies_after_grouping(store):
    for name in ("a", "b", "c"):
        store.add(name, "user", "jarvis", "tema común")
        store.add(name, "assistant", "jarvis", "tema común")

    assert [c.id for c in store.search_conversations("tema")] == ["c", "b", "a"]
    assert [c.id for c in store.search_conversations("tema", limit=2)] == ["c", "b"]


def test_search_default_limit_is_20(store):
    for n in range(21):
        store.add(f"c{n}", "user", "jarvis", "tema")

    assert len(store.search_conversations("tema")) == 20


def test_delete_removes_only_that_conversation(tmp_path, store):
    store.add("a", "user", "jarvis", "uno")
    store.add("a", "assistant", "jarvis", "dos")
    store.add("b", "user", "jarvis", "tres")

    assert store.delete_conversation("a") is True

    assert [row[0] for row in rows(tmp_path)] == ["b"]


def test_delete_unknown_id_returns_false_and_changes_nothing(tmp_path, store):
    store.add("a", "user", "jarvis", "uno")

    assert store.delete_conversation("nope") is False

    assert [row[0] for row in rows(tmp_path)] == ["a"]


def test_has_conversation(store):
    store.add("a", "user", "jarvis", "uno")

    assert store.has_conversation("a") is True
    assert store.has_conversation("nope") is False
