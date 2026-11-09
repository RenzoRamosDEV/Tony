import sqlite3

import pytest

from tests.core.orchestrator.test_runtime import DONE, NO_PIN, Harness, home_for
from tests.fakes.fake_engine import FakeModelEngine, Final
from tests.fakes.routines import run_statuses, seed_due_routine
from tony.core.automation.store import ROUTINES_FILE


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


async def test_scheduler_runs_a_due_routine_with_a_routine_task_event(tmp_path):
    home, _ = home_for(tmp_path, NO_PIN)
    seed_due_routine(home)
    worker = FakeModelEngine([Final(structured=DONE)])

    async with Harness(home, worker=worker) as harness:
        await harness.until(lambda: run_statuses(home) == ["ok"])

    [started] = harness.of("task_started")
    assert started["origin"] == "routine" and started["objetivo"] == "resume mis notas"


async def test_scheduler_failure_is_published_and_the_runtime_keeps_going(tmp_path):
    home, _ = home_for(tmp_path, NO_PIN)
    seed_due_routine(home)
    connection = sqlite3.connect(home / ROUTINES_FILE)
    connection.execute("UPDATE routines SET timezone = 'Not/AZone'")
    connection.commit()
    connection.close()

    async with Harness(home) as harness:
        [error] = await harness.wait_for("error")
        harness.send(type="set_mode", mode="text")
        await harness.wait_for("reply_mode", 2)

    assert error["source"] == "routines"


async def test_scheduler_stops_with_the_runtime(tmp_path):
    home, _ = home_for(tmp_path, NO_PIN)

    async with Harness(home) as harness:
        scheduler = harness.runtime.scheduler
        assert not scheduler.task.done()

    assert scheduler.task.done()
