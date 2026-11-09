from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from tests.apps.test_cli_chat import NO_PIN_POLICY
from tests.core.orchestrator.tony_home import make_tony_home
from tony.apps.cli.main import create_app
from tony.core.config.placeholders import SecretMasker
from tony.core.memory.actions import ACTIONS_FILE, ActionJournal

START = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def home(tmp_path):
    return make_tony_home(tmp_path, policy=NO_PIN_POLICY)[0]


def seed(home, *rows):
    """rows: (tool, final state or None, detail); each is created one minute after the last."""
    moment = {"now": START}
    journal = ActionJournal(home, SecretMasker(), clock=lambda: moment["now"])
    ids = []
    for tool, state, detail in rows:
        call_id = journal.prepared("t1", "viernes", tool, "d" * 64)
        if state:
            journal.transition(call_id, state, detail)
        ids.append(call_id)
        moment["now"] += timedelta(minutes=1)
    journal.close()
    return ids


def run(home, *args):
    return CliRunner().invoke(create_app(), list(args), env={"TONY_HOME": str(home)})


def data_rows(result):
    return [line.split() for line in result.stdout.splitlines()[1:]]


def test_list_prints_newest_first_with_the_columns(home):
    ids = seed(home, ("a.tool", "succeeded", ""), ("b.tool", "failed", "boom"))

    result = run(home, "actions", "list")

    assert result.exit_code == 0
    assert result.stdout.splitlines()[0].split() == ["call", "time", "state", "agent", "tool"]
    rows = data_rows(result)
    assert [row[0] for row in rows] == [ids[1], ids[0]]
    assert rows[0][2:] == ["failed", "viernes", "b.tool"]
    assert "2026-11-01" in rows[0][1]


def test_list_default_limit_is_20(home):
    seed(home, *[("x.tool", None, "")] * 25)

    assert len(data_rows(run(home, "actions", "list"))) == 20


def test_list_limit_option(home):
    seed(home, *[("x.tool", None, "")] * 5)

    assert len(data_rows(run(home, "actions", "list", "--limit", "2"))) == 2


def test_list_state_filter(home):
    seed(
        home,
        ("a", "outcome_unknown", "x"),
        ("b", "succeeded", ""),
        ("c", "outcome_unknown", "x"),
        ("d", None, ""),
        ("e", "failed", ""),
    )

    result = run(home, "actions", "list", "--state", "outcome_unknown")

    assert [row[4] for row in data_rows(result)] == ["c", "a"]
    assert {row[2] for row in data_rows(result)} == {"outcome_unknown"}


@pytest.mark.parametrize("home_has_file", [False, True])
def test_list_empty_or_missing_file_prints_a_message(home, home_has_file):
    if home_has_file:
        seed(home)

    result = run(home, "actions", "list")

    assert result.exit_code == 0
    assert "no actions" in result.stdout.lower()


def test_listing_a_missing_journal_creates_nothing(home):
    run(home, "actions", "list")

    assert not (home / ACTIONS_FILE).exists()


def test_bad_state_exits_2_naming_the_valid_ones(home):
    result = run(home, "actions", "list", "--state", "bogus")

    assert result.exit_code == 2
    assert "bogus" in result.output
    assert "outcome_unknown" in result.output and "dispatched" in result.output


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_non_positive_limit_exits_2(home, limit):
    result = run(home, "actions", "list", "--limit", limit)

    assert result.exit_code == 2


def test_show_prints_every_column(home):
    [call_id] = seed(home, ("gmail.send_email", "failed", "smtp down"))

    result = run(home, "actions", "show", call_id)

    assert result.exit_code == 0
    fields = dict(line.split(": ", 1) for line in result.stdout.splitlines())
    assert fields["call_id"] == call_id
    assert (fields["task_id"], fields["agent"], fields["tool"]) == (
        "t1",
        "viernes",
        "gmail.send_email",
    )
    assert (fields["state"], fields["detail"]) == ("failed", "smtp down")
    assert fields["args_digest"] == "d" * 64
    assert set(fields) >= {"created_at", "updated_at"}


def test_show_unknown_id_exits_2_naming_it(home):
    seed(home, ("a", None, ""))

    result = run(home, "actions", "show", "zzz")

    assert result.exit_code == 2
    assert "zzz" in result.output


def test_show_with_no_journal_exits_2(home):
    assert run(home, "actions", "show", "zzz").exit_code == 2


def test_outcome_unknown_is_reported_as_such(home):
    [call_id] = seed(home, ("a", "outcome_unknown", "timed out after 20 s"))

    listed = run(home, "actions", "list").stdout
    shown = run(home, "actions", "show", call_id).stdout

    assert "outcome_unknown" in listed and "state: outcome_unknown" in shown
    assert "succeeded" not in listed + shown


def test_inspection_does_not_run_recovery(home):
    ids = seed(home, ("a", "dispatched", ""))

    run(home, "actions", "list")
    run(home, "actions", "show", ids[0])

    assert "state: dispatched" in run(home, "actions", "show", ids[0]).stdout
