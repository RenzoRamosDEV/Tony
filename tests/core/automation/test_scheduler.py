import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tony.core.automation.occurrences import Occurrence
from tony.core.automation.scheduler import RoutineScheduler, RunOutcome
from tony.core.automation.store import RoutineStore
from tony.core.config.placeholders import SecretMasker

T0 = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
DUE = "1:2026-11-02:08:30"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class FakeRun:
    def __init__(self, outcome=None):
        self.outcome = outcome or RunOutcome(ok=True, text="hecho")
        self.routines = []
        self.error = None

    async def __call__(self, routine):
        self.routines.append(routine)
        if self.error:
            raise self.error
        return self.outcome


class Lock:
    def __init__(self, unlocked=True):
        self.unlocked = unlocked

    def __call__(self):
        return self.unlocked


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    opened = RoutineStore(tmp_path, clock=clock, masker=SecretMasker({"s3cr3t"}))
    opened.add(name="r", prompt="haz algo", time="08:30", weekdays=None, timezone="UTC")
    yield opened
    opened.close()


def make(store, clock, run=None, lock=None, published=None):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    scheduler = RoutineScheduler(
        store,
        run or FakeRun(),
        clock=clock,
        unlocked=lock or Lock(),
        sleep=sleep,
        publish=(published if published is not None else []).append,
    )
    scheduler.sleeps = sleeps
    return scheduler


def statuses(store):
    return {run.occurrence_id: run.status for run in store.runs()}


async def test_nothing_before_the_time(store, clock):
    run = FakeRun()

    await make(store, clock, run).tick()

    assert run.routines == [] and store.runs() == []


async def test_due_occurrence_runs_once_across_ticks(store, clock):
    run = FakeRun()
    scheduler = make(store, clock, run)
    clock.advance(minutes=31)

    await scheduler.tick()
    await scheduler.tick()

    assert [r.id for r in run.routines] == [1]
    assert run.routines[0].prompt == "haz algo"
    assert statuses(store) == {DUE: "ok"}
    assert store.runs()[0].result == "hecho"


async def test_second_scheduler_on_the_same_database_does_not_rerun(tmp_path, store, clock):
    run_a, run_b = FakeRun(), FakeRun()
    other = RoutineStore(tmp_path, clock=clock)
    clock.advance(minutes=31)

    await make(store, clock, run_a).tick()
    await make(other, clock, run_b).tick()

    assert len(run_a.routines) == 1 and run_b.routines == []
    other.close()


async def test_late_over_twelve_hours_is_skipped_without_a_task(store, clock):
    run = FakeRun()
    clock.advance(hours=13, minutes=30)

    await make(store, clock, run).tick()

    assert statuses(store) == {DUE: "skipped"} and run.routines == []


async def test_late_by_one_hour_runs(store, clock):
    run = FakeRun()
    clock.advance(hours=1, minutes=30)

    await make(store, clock, run).tick()

    assert statuses(store) == {DUE: "ok"} and len(run.routines) == 1


async def test_locked_stays_queued_and_runs_after_unlock(store, clock):
    run, lock = FakeRun(), Lock(unlocked=False)
    scheduler = make(store, clock, run, lock)
    clock.advance(minutes=31)

    await scheduler.tick()
    assert statuses(store) == {DUE: "queued"} and run.routines == []

    lock.unlocked = True
    await scheduler.tick()
    assert statuses(store) == {DUE: "ok"}


async def test_queued_past_twelve_hours_becomes_skipped(store, clock):
    run, lock = FakeRun(), Lock(unlocked=False)
    scheduler = make(store, clock, run, lock)
    clock.advance(minutes=31)
    await scheduler.tick()
    clock.advance(hours=12)
    lock.unlocked = True

    await scheduler.tick()

    assert statuses(store) == {DUE: "skipped"} and run.routines == []


async def test_error_outcome_is_recorded_with_the_text(store, clock):
    run = FakeRun(RunOutcome(ok=False, text="falló"))
    clock.advance(minutes=31)

    await make(store, clock, run).tick()

    assert (store.runs()[0].status, store.runs()[0].result) == ("error", "falló")


async def test_result_is_masked_and_capped(store, clock):
    run = FakeRun(RunOutcome(ok=True, text="s3cr3t " + "x" * 3000))
    clock.advance(minutes=31)

    await make(store, clock, run).tick()

    result = store.runs()[0].result
    assert "s3cr3t" not in result and len(result) == 2000


async def test_stale_claim_is_marked_interrupted_and_not_rerun(store, clock):
    run = FakeRun()
    clock.advance(minutes=31)
    store.record(1, Occurrence(DUE, T0 + timedelta(minutes=30)), "queued")
    store.claim(DUE)
    clock.advance(seconds=601)

    await make(store, clock, run).tick()

    assert (store.runs()[0].status, store.runs()[0].result) == ("error", "interrupted")
    assert run.routines == []


async def test_raising_run_publishes_an_error_and_the_next_tick_works(store, clock):
    run, published = FakeRun(), []
    run.error = RuntimeError("boom")
    scheduler = make(store, clock, run, published=published)
    clock.advance(minutes=31)

    await scheduler.tick()

    assert statuses(store) == {DUE: "error"}
    assert [e["type"] for e in published] == ["error"]
    assert published[0]["source"] == "routines" and "boom" in published[0]["message"]
    run.error = None
    clock.advance(days=1)
    await scheduler.tick()
    assert statuses(store)["1:2026-11-03:08:30"] == "ok"


async def test_disabled_routine_creates_no_occurrences(store, clock):
    store.set_enabled(1, False)
    clock.advance(minutes=31)

    await make(store, clock).tick()

    assert store.runs() == []


async def test_removed_routine_with_a_queued_run_is_not_run(store, clock):
    run, lock = FakeRun(), Lock(unlocked=False)
    scheduler = make(store, clock, run, lock)
    clock.advance(minutes=31)
    await scheduler.tick()
    store.remove(1)
    lock.unlocked = True

    await scheduler.tick()

    assert run.routines == [] and statuses(store) == {DUE: "skipped"}


async def test_run_forever_ticks_sleeps_and_survives_a_failing_tick(store, clock):
    published = []
    scheduler = make(store, clock, published=published)
    calls = {"n": 0}

    async def tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("tick broke")
        if calls["n"] == 3:
            raise KeyboardInterrupt

    scheduler.tick = tick

    with pytest.raises(KeyboardInterrupt):
        await scheduler.run_forever()

    assert calls["n"] == 3 and scheduler.sleeps == [30, 30]
    assert published[0]["type"] == "error" and "tick broke" in published[0]["message"]


async def test_scheduler_has_no_pin_prompt_dependency(store, clock):
    lock = Lock(unlocked=False)
    scheduler = make(store, clock, FakeRun(), lock)
    clock.advance(minutes=31)

    await scheduler.tick()

    assert not hasattr(scheduler, "gate") and lock.unlocked is False


async def test_one_unschedulable_routine_is_reported_and_others_still_run(store, clock):
    store.add(name="rota", prompt="x", time="08:30", weekdays=None, timezone="UTC")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE routines SET timezone = 'Not/AZone' WHERE id = 1")
    run, published = FakeRun(), []
    clock.advance(minutes=31)

    await make(store, clock, run, published=published).tick()

    assert [r.id for r in run.routines] == [2]
    assert "cannot be scheduled" in published[0]["message"]


async def test_disabled_routine_with_a_queued_run_is_skipped(store, clock):
    run, lock = FakeRun(), Lock(unlocked=False)
    scheduler = make(store, clock, run, lock)
    clock.advance(minutes=31)
    await scheduler.tick()
    store.set_enabled(1, False)
    lock.unlocked = True

    await scheduler.tick()

    assert run.routines == [] and statuses(store) == {DUE: "skipped"}
