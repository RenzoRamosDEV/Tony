import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tony.core.automation.occurrences import Occurrence
from tony.core.automation.routine import RoutineError
from tony.core.automation.store import ROUTINES_FILE, RoutineStore, local_zone_name

T0 = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    opened = RoutineStore(tmp_path, clock=clock)
    yield opened
    opened.close()


def add(store, **overrides):
    values = {
        "name": "mañana",
        "prompt": "resume",
        "time": "08:30",
        "weekdays": None,
        "timezone": "UTC",
    }
    return store.add(**{**values, **overrides})


def occurrence(routine_id=1, day="2026-11-02", at=T0):
    return Occurrence(f"{routine_id}:{day}:08:30", at)


def test_add_defaults_and_list(store, clock):
    routine_id = add(store)

    (routine,) = store.routines()
    assert routine.id == routine_id
    assert (routine.name, routine.prompt, routine.time, routine.timezone) == (
        "mañana",
        "resume",
        "08:30",
        "UTC",
    )
    assert routine.weekdays == 127 and routine.enabled
    assert routine.active_since == clock.now


def test_add_normalises_time_and_parses_weekdays(store):
    add(store, time="8:05", weekdays="Mon, wed")

    (routine,) = store.routines()
    assert routine.time == "08:05" and routine.weekdays == 0b101


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("time", "25:00", "invalid time"),
        ("time", "8h", "invalid time"),
        ("weekdays", "mon,xyz", "invalid weekday"),
        ("timezone", "Mars/Base", "unknown timezone"),
        ("timezone", "../etc", "unknown timezone"),
        ("prompt", "   ", "prompt"),
        ("name", "", "name"),
    ],
)
def test_validation_rejects_and_stores_nothing(store, field, value, message):
    with pytest.raises(RoutineError, match=message):
        add(store, **{field: value})

    assert store.routines() == []


def test_remove_enable_disable(store, clock):
    routine_id = add(store)

    assert store.set_enabled(routine_id, False)
    assert not store.routines()[0].enabled
    clock.advance(hours=1)
    assert store.set_enabled(routine_id, True)
    enabled = store.routines()[0]
    assert enabled.enabled and enabled.active_since == clock.now
    assert store.remove(routine_id)
    assert store.routines() == []


def test_unknown_ids(store):
    assert not store.remove(99)
    assert not store.set_enabled(99, True)
    assert store.get(99) is None


def test_ids_are_not_reused(store):
    first = add(store)
    store.remove(first)

    assert add(store) == first + 1


def test_record_is_unique_per_occurrence(store):
    routine_id = add(store)

    assert store.record(routine_id, occurrence(), "queued")
    assert not store.record(routine_id, occurrence(), "queued")
    assert len(store.runs()) == 1


def test_queued_runs_oldest_first(store):
    routine_id = add(store)
    store.record(routine_id, occurrence(day="2026-11-03", at=T0 + timedelta(days=1)), "queued")
    store.record(routine_id, occurrence(), "queued")
    store.record(routine_id, occurrence(day="2026-11-04", at=T0), "skipped")

    queued = store.queued()

    assert [run.occurrence_id for run in queued] == ["1:2026-11-02:08:30", "1:2026-11-03:08:30"]
    assert queued[0].scheduled_for == T0 and queued[0].routine_id == routine_id


def test_claim_has_a_single_winner(tmp_path, clock):
    first, second = RoutineStore(tmp_path, clock=clock), RoutineStore(tmp_path, clock=clock)
    routine_id = add(first)
    first.record(routine_id, occurrence(), "queued")

    assert first.claim("1:2026-11-02:08:30")
    assert not second.claim("1:2026-11-02:08:30")
    assert first.runs()[0].started_at == clock.now
    first.close()
    second.close()


def test_finish_stores_status_and_masked_result(tmp_path, clock):
    from tony.core.config.placeholders import SecretMasker

    masked = RoutineStore(tmp_path, clock=clock, masker=SecretMasker({"s3cr3t"}))
    routine_id = add(masked)
    masked.record(routine_id, occurrence(), "queued")

    masked.finish("1:2026-11-02:08:30", "ok", "clave s3cr3t " + "x" * 3000)

    (run,) = masked.runs()
    assert run.status == "ok" and "s3cr3t" not in run.result
    assert len(run.result) == 2000
    masked.close()


def test_skip_marks_queued_run(store):
    routine_id = add(store)
    store.record(routine_id, occurrence(), "queued")

    store.skip("1:2026-11-02:08:30")

    assert store.runs()[0].status == "skipped" and store.queued() == []


def test_stale_claims_become_interrupted_errors(store, clock):
    routine_id = add(store)
    store.record(routine_id, occurrence(), "queued")
    store.claim("1:2026-11-02:08:30")
    clock.advance(seconds=600)
    assert store.interrupt_stale(timedelta(seconds=600)) == 0
    clock.advance(seconds=1)

    assert store.interrupt_stale(timedelta(seconds=600)) == 1

    (run,) = store.runs()
    assert (run.status, run.result) == ("error", "interrupted")
    assert store.queued() == []


def test_inbox_newest_first_keeps_removed_routines(store):
    routine_id = add(store)
    store.record(routine_id, occurrence(), "queued")
    store.finish("1:2026-11-02:08:30", "ok", "hecho\nsegunda línea")
    store.record(routine_id, occurrence(day="2026-11-03", at=T0 + timedelta(days=1)), "skipped")
    store.remove(routine_id)

    inbox = store.inbox(limit=10)

    assert [row.occurrence_id for row in inbox] == ["1:2026-11-03:08:30", "1:2026-11-02:08:30"]
    assert inbox[1].routine_name is None and inbox[1].result == "hecho\nsegunda línea"
    assert len(store.inbox(limit=1)) == 1


def test_last_occurrence_is_updated(store):
    routine_id = add(store)

    store.record(routine_id, occurrence(), "queued")

    row = sqlite3.connect(store.path).execute("SELECT last_occurrence FROM routines").fetchone()
    assert row == ("1:2026-11-02:08:30",)


def test_file_location(store, tmp_path):
    assert store.path == tmp_path / ROUTINES_FILE


@pytest.mark.parametrize(
    ("environ", "link", "expected"),
    [
        ({"TZ": "Europe/Madrid"}, None, "Europe/Madrid"),
        ({"TZ": "Not/AZone"}, "/usr/share/zoneinfo/Asia/Tokyo", "Asia/Tokyo"),
        ({}, "/usr/share/zoneinfo/America/New_York", "America/New_York"),
        ({}, "/somewhere/else", "UTC"),
        ({}, None, "UTC"),
    ],
)
def test_local_zone_name(environ, link, expected):
    assert local_zone_name(environ, read_link=lambda: link) == expected
