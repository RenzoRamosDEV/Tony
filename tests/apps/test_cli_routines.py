from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from tony.apps.cli.main import create_app
from tony.core.automation.occurrences import Occurrence
from tony.core.automation.store import RoutineStore

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TZ", "Europe/Madrid")


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def run(home, *args):
    app = create_app(now=lambda: NOW)
    return CliRunner().invoke(app, ["routines", *args], env={"TONY_HOME": str(home)})


def add(home, name="mañana", *extra):
    return run(home, "add", name, "--time", "08:30", "--prompt", "resume mis tareas", *extra)


def test_add_with_defaults_prints_the_id_and_lists_it(home):
    added = add(home)

    listed = run(home, "list")

    assert added.exit_code == 0 and added.stdout.strip() == "routine 1 added"
    header, row = listed.stdout.splitlines()
    assert header.split() == ["id", "name", "time", "weekdays", "timezone", "enabled"]
    assert row.split() == ["1", "mañana", "08:30", "daily", "Europe/Madrid", "yes"]


def test_add_with_options(home):
    add(home, "lunes", "--weekdays", "mon,wed", "--tz", "UTC")

    row = run(home, "list").stdout.splitlines()[1].split()

    assert row[3:] == ["mon,wed", "UTC", "yes"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--tz", "Mars/Base"], "Mars/Base"),
        (["--weekdays", "mon,zzz"], "zzz"),
    ],
)
def test_invalid_options_are_usage_errors_and_store_nothing(home, extra, message):
    result = add(home, "x", *extra)

    assert result.exit_code == 2 and message in result.output
    assert run(home, "list").stdout.strip() == "no routines"


def test_invalid_time_and_empty_prompt(home):
    bad_time = run(home, "add", "x", "--time", "25:00", "--prompt", "p")
    empty = run(home, "add", "x", "--time", "08:30", "--prompt", "  ")

    assert bad_time.exit_code == 2 and "25:00" in bad_time.output
    assert empty.exit_code == 2 and "prompt" in empty.output
    assert run(home, "list").stdout.strip() == "no routines"


def test_disable_enable_remove(home):
    add(home)

    assert run(home, "disable", "1").exit_code == 0
    assert run(home, "list").stdout.splitlines()[1].split()[-1] == "no"
    assert run(home, "enable", "1").exit_code == 0
    assert run(home, "list").stdout.splitlines()[1].split()[-1] == "yes"
    assert run(home, "remove", "1").exit_code == 0
    assert run(home, "list").stdout.strip() == "no routines"


@pytest.mark.parametrize("command", ["remove", "enable", "disable"])
def test_unknown_id_is_a_usage_error(home, command):
    result = run(home, command, "99")

    assert result.exit_code == 2 and "tony: unknown routine 99" in result.output


def seed_runs(home):
    store = RoutineStore(home, clock=lambda: NOW)
    routine_id = store.add(name="mañana", prompt="p", time="08:30", weekdays=None, timezone="UTC")
    for day, status, result in [(2, "ok", "primera línea\nsegunda"), (3, "error", "boom")]:
        occurrence = Occurrence(f"{routine_id}:2026-11-0{day}:08:30", NOW + timedelta(days=day))
        store.record(routine_id, occurrence, "queued")
        store.finish(occurrence.id, status, result)
    store.remove(routine_id)
    store.close()


def test_inbox_newest_first_with_first_line_and_removed_routines(home):
    seed_runs(home)

    lines = run(home, "inbox").stdout.splitlines()

    assert lines[0].split() == ["occurrence", "routine", "status", "result"]
    assert lines[1].split() == ["1:2026-11-03:08:30", "-", "error", "boom"]
    assert lines[2].split() == ["1:2026-11-02:08:30", "-", "ok", "primera", "línea"]


def test_inbox_limit_and_empty(home):
    assert run(home, "inbox").stdout.strip() == "no routine runs"
    seed_runs(home)

    assert len(run(home, "inbox", "--limit", "1").stdout.splitlines()) == 2
    assert run(home, "inbox", "--limit", "0").exit_code == 2


def test_commands_start_no_task(home):
    result = add(home)

    assert result.exit_code == 0
    assert not (home / "logs").exists()
