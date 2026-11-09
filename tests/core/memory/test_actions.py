import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.memory.actions import ACTIONS_FILE, ActionJournal, open_journal

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal(tmp_path, clock):
    store = ActionJournal(tmp_path, SecretMasker({"s3cr3t"}), clock=clock)
    yield store
    store.close()


def prepare(journal, tool="gmail.send_email", task="t1"):
    return journal.prepared(task, "viernes", tool, "d" * 64)


def test_schema_has_the_contract_columns(tmp_path, journal):
    connection = sqlite3.connect(tmp_path / ACTIONS_FILE)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(actions)")]
    finally:
        connection.close()

    assert columns == [
        "call_id",
        "task_id",
        "agent",
        "tool",
        "args_digest",
        "state",
        "created_at",
        "updated_at",
        "detail",
    ]


def test_prepared_creates_a_row_with_a_fresh_uuid(journal):
    first, second = prepare(journal), prepare(journal)

    record = journal.get(first)
    assert first != second
    assert (record.task_id, record.agent, record.tool) == ("t1", "viernes", "gmail.send_email")
    assert (record.args_digest, record.state, record.detail) == ("d" * 64, "prepared", "")
    assert record.created_at == record.updated_at == T0.isoformat(timespec="microseconds")


def test_transition_updates_state_detail_and_updated_at(journal, clock):
    call_id = prepare(journal)
    clock.advance(5)

    journal.transition(call_id, "dispatched")
    journal.transition(call_id, "failed", "boom")

    record = journal.get(call_id)
    assert (record.state, record.detail) == ("failed", "boom")
    assert record.created_at != record.updated_at
    assert record.updated_at == (T0 + timedelta(seconds=5)).isoformat(timespec="microseconds")


def test_detail_secret_is_masked(journal):
    call_id = prepare(journal)

    journal.transition(call_id, "failed", "auth s3cr3t rejected")

    assert journal.get(call_id).detail == "auth *** rejected"


@pytest.mark.parametrize(("length", "kept"), [(199, 199), (200, 200), (201, 200)])
def test_detail_is_cut_to_200_characters(journal, length, kept):
    call_id = prepare(journal)

    journal.transition(call_id, "failed", "x" * length)

    assert len(journal.get(call_id).detail) == kept


def test_arguments_are_never_stored(tmp_path, journal):
    prepare(journal)

    raw = (tmp_path / ACTIONS_FILE).read_bytes()
    assert b"args" not in raw.replace(b"args_digest", b"")


def test_get_unknown_is_none(journal):
    assert journal.get("nope") is None


def test_recover_moves_only_older_dispatched_rows(journal, clock):
    old_dispatched, old_prepared, old_done = (prepare(journal) for _ in range(3))
    journal.transition(old_dispatched, "dispatched")
    journal.transition(old_done, "succeeded")
    clock.advance(10)
    fresh = prepare(journal)
    journal.transition(fresh, "dispatched")

    recovered = journal.recover_interrupted(T0 + timedelta(seconds=5))

    assert recovered == 1
    states = {id: journal.get(id).state for id in (old_dispatched, old_prepared, old_done, fresh)}
    assert states == {
        old_dispatched: "outcome_unknown",
        old_prepared: "prepared",
        old_done: "succeeded",
        fresh: "dispatched",
    }
    assert "interrupted" in journal.get(old_dispatched).detail


def test_recover_boundary_row_updated_exactly_at_process_start_is_kept(journal):
    call_id = prepare(journal)
    journal.transition(call_id, "dispatched")

    journal.recover_interrupted(T0)

    assert journal.get(call_id).state == "dispatched"


def test_list_is_newest_first_and_limited(journal, clock):
    ids = []
    for _ in range(3):
        ids.append(prepare(journal))
        clock.advance(1)
    ids.append(prepare(journal))
    ids.append(prepare(journal))

    assert [r.call_id for r in journal.list(limit=3)] == ids[::-1][:3]


def test_list_filters_by_state(journal):
    a, b, c = (prepare(journal) for _ in range(3))
    journal.transition(a, "outcome_unknown")
    journal.transition(c, "outcome_unknown")

    assert {r.call_id for r in journal.list(state="outcome_unknown")} == {a, c}
    assert [r.call_id for r in journal.list(state="prepared")] == [b]


def test_list_limit_one_returns_the_newest(journal, clock):
    prepare(journal)
    clock.advance(1)
    newest = prepare(journal)

    assert [r.call_id for r in journal.list(limit=1)] == [newest]


def test_open_journal_of_a_missing_file_is_none_and_creates_nothing(tmp_path):
    assert open_journal(tmp_path, SecretMasker()) is None
    assert not (tmp_path / ACTIONS_FILE).exists()


def test_open_journal_reads_an_existing_file(tmp_path, journal):
    call_id = prepare(journal)

    reader = open_journal(tmp_path, SecretMasker())
    try:
        assert reader.get(call_id).state == "prepared"
    finally:
        reader.close()


def test_for_task_lists_only_that_task_oldest_first(journal, clock):
    first = prepare(journal, task="t1")
    clock.advance(1)
    other = prepare(journal, task="t2")
    clock.advance(1)
    second = prepare(journal, tool="shell.run", task="t1")

    assert [r.call_id for r in journal.for_task("t1")] == [first, second]
    assert [r.call_id for r in journal.for_task("t2")] == [other]
    assert journal.for_task("nope") == []


def test_for_task_filters_by_state(journal):
    done, pending = prepare(journal), prepare(journal)
    journal.transition(done, "succeeded")

    assert [r.call_id for r in journal.for_task("t1", "succeeded")] == [done]
    assert len(journal.for_task("t1")) == 2
    assert pending
