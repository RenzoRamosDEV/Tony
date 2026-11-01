import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from tests.fakes.fake_engine import FakeModelEngine
from tony.apps.cli.main import create_app

UTC_PLUS_ONE = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC_PLUS_ONE)
HEADER = ["ts", "agent", "tool", "verdict", "rule", "user_decision"]


def line(ts, verdict="allow", rule="r/allow", user_decision=None, tool="filesystem.read_file"):
    return {
        "ts": ts,
        "task_id": "t",
        "agent": "viernes",
        "tool": tool,
        "args_hash": "h",
        "args_preview": "{}",
        "verdict": verdict,
        "rule": rule,
        "user_decision": user_decision,
        "duration_ms": 1,
    }


def write_audit(home, *lines):
    (home / "logs").mkdir(parents=True, exist_ok=True)
    text = "".join(item if isinstance(item, str) else json.dumps(item) + "\n" for item in lines)
    (home / "logs" / "audit.jsonl").write_text(text)


def audit(home, *args):
    app = create_app(engine_factory=lambda: FakeModelEngine([]), now=lambda: NOW)
    return CliRunner().invoke(app, ["audit", *args], env={"TONY_HOME": str(home)})


def rows(output):
    return [row.split() for row in output.splitlines()]


def test_prints_header_and_lines_oldest_first(tmp_path):
    write_audit(
        tmp_path,
        line("2026-11-01T09:00:00Z"),
        line("2026-11-01T10:00:00Z", "confirm", "fs.delete*/confirm", "allow", "fs.delete_file"),
    )

    result = audit(tmp_path)

    assert result.exit_code == 0
    assert rows(result.stdout) == [
        HEADER,
        ["2026-11-01T09:00:00Z", "viernes", "filesystem.read_file", "allow", "r/allow", "-"],
        [
            "2026-11-01T10:00:00Z",
            "viernes",
            "fs.delete_file",
            "confirm",
            "fs.delete*/confirm",
            "allow",
        ],
    ]


def test_table_exact_text(tmp_path):
    write_audit(tmp_path, line("2026-11-01T09:00:00Z", "deny", "default", tool="foo.bar"))

    assert audit(tmp_path).stdout == (
        "ts                    agent    tool     verdict  rule     user_decision\n"
        "2026-11-01T09:00:00Z  viernes  foo.bar  deny     default  -\n"
    )


def test_columns_are_aligned(tmp_path):
    write_audit(tmp_path, line("2026-11-01T09:00:00Z"), line("2026-11-01T09:00:01Z", tool="x.y"))

    header, first, second = audit(tmp_path).stdout.splitlines()

    assert header.index("agent") == first.index("viernes") == second.index("viernes")
    assert header.index("verdict") == first.index("allow") == second.index("allow")


def test_filter_by_verdict(tmp_path):
    write_audit(
        tmp_path,
        line("2026-11-01T09:00:00Z", "allow"),
        line("2026-11-01T09:01:00Z", "deny", "shell.run/deny"),
    )

    result = audit(tmp_path, "--verdict", "deny")

    assert result.exit_code == 0
    assert [row[3] for row in rows(result.stdout)[1:]] == ["deny"]


def test_today_uses_the_local_date(tmp_path):
    write_audit(tmp_path, line("2026-10-31T23:30:00Z"), line("2026-10-31T22:30:00Z"))

    result = audit(tmp_path, "--today")

    assert [row[0] for row in rows(result.stdout)[1:]] == ["2026-10-31T23:30:00Z"]


def test_today_follows_the_timezone_of_now_not_the_machine(tmp_path):
    utc_minus_five = timezone(timedelta(hours=-5))
    write_audit(tmp_path, line("2026-10-31T15:30:00Z"), line("2026-11-01T04:30:00Z"))
    app = create_app(
        engine_factory=lambda: FakeModelEngine([]),
        now=lambda: datetime(2026, 10, 31, 20, 0, tzinfo=utc_minus_five),
    )

    result = CliRunner().invoke(app, ["audit", "--today"], env={"TONY_HOME": str(tmp_path)})

    assert [row[0] for row in rows(result.stdout)[1:]] == [
        "2026-10-31T15:30:00Z",
        "2026-11-01T04:30:00Z",
    ]


def test_filters_combine(tmp_path):
    write_audit(
        tmp_path,
        line("2026-11-01T09:00:00Z", "deny"),
        line("2026-11-01T09:00:00Z", "allow"),
        line("2026-10-30T09:00:00Z", "deny"),
    )

    result = audit(tmp_path, "--today", "--verdict", "deny")

    assert len(rows(result.stdout)) == 2


def test_missing_file_prints_header_only(tmp_path):
    result = audit(tmp_path)

    assert result.exit_code == 0
    assert rows(result.stdout) == [HEADER]
    assert result.stderr == ""


def test_no_match_prints_header_only(tmp_path):
    write_audit(tmp_path, line("2026-11-01T09:00:00Z", "allow"))

    result = audit(tmp_path, "--verdict", "confirm")

    assert (result.exit_code, rows(result.stdout)) == (0, [HEADER])


def test_malformed_lines_skipped_with_one_warning(tmp_path):
    write_audit(tmp_path, "no json\n", line("2026-11-01T09:00:00Z"), "[1, 2]\n", '{"ts": \n')

    result = audit(tmp_path)

    assert result.exit_code == 0
    assert len(rows(result.stdout)) == 2
    assert result.stderr == "tony: skipped 3 malformed lines in logs/audit.jsonl\n"


@pytest.mark.parametrize("verdict", ["maybe", "ALLOW", ""])
def test_invalid_verdict_option_is_a_usage_error(tmp_path, verdict):
    result = audit(tmp_path, "--verdict", verdict)

    assert result.exit_code == 2
    assert "verdict" in result.stderr


def test_help_lists_audit(tmp_path):
    result = audit(tmp_path, "--help")

    app = create_app(engine_factory=lambda: FakeModelEngine([]))
    top = CliRunner().invoke(app, ["--help"])
    assert "audit" in top.stdout
    assert "--today" in result.stdout and "--verdict" in result.stdout
