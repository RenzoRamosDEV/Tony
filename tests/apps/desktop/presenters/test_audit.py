import json
from datetime import datetime, timedelta, timezone

from tony.apps.desktop.presenters.audit import audit_today
from tony.core.guard.audit import AUDIT_FILE

MADRID = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=MADRID)


def audit_line(ts, verdict, tool="filesystem.read_file", decision=None):
    return {
        "ts": ts,
        "task_id": "t",
        "agent": "viernes",
        "tool": tool,
        "args_hash": "h",
        "args_preview": '{"path": "s3cr3t.md"}',
        "verdict": verdict,
        "rule": f"r/{verdict}",
        "user_decision": decision,
        "duration_ms": 1,
    }


def write_audit(root, lines):
    path = root / AUDIT_FILE
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_only_lines_of_the_local_day_with_local_times(tmp_path):
    write_audit(
        tmp_path,
        [
            audit_line("2026-10-31T22:59:59Z", "allow"),
            audit_line("2026-10-31T23:00:00Z", "deny", "shell.run"),
            audit_line("2026-11-01T10:30:00Z", "confirm", "filesystem.delete_file", "allow"),
            audit_line("2026-11-01T22:59:59Z", "allow", "last"),
            audit_line("2026-11-01T23:00:00Z", "allow"),
        ],
    )

    rows = audit_today(tmp_path, NOW)

    assert rows == [
        {
            "time": "00:00:00",
            "agent": "viernes",
            "tool": "shell.run",
            "verdict": "deny",
            "rule": "r/deny",
            "user_decision": None,
        },
        {
            "time": "11:30:00",
            "agent": "viernes",
            "tool": "filesystem.delete_file",
            "verdict": "confirm",
            "rule": "r/confirm",
            "user_decision": "allow",
        },
        {
            "time": "23:59:59",
            "agent": "viernes",
            "tool": "last",
            "verdict": "allow",
            "rule": "r/allow",
            "user_decision": None,
        },
    ]


def test_rows_never_carry_tool_arguments(tmp_path):
    write_audit(tmp_path, [audit_line("2026-11-01T10:00:00Z", "allow")])

    [row] = audit_today(tmp_path, NOW)

    assert set(row) == {"time", "agent", "tool", "verdict", "rule", "user_decision"}
    assert "s3cr3t" not in json.dumps(row)


def test_missing_audit_file_gives_no_rows(tmp_path):
    assert audit_today(tmp_path, NOW) == []
