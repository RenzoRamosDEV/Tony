import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tony.apps.desktop.presenters.edith import EdithPresenter
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling, TaskResult
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
        "args_preview": "{}",
        "verdict": verdict,
        "rule": f"r/{verdict}",
        "user_decision": decision,
        "duration_ms": 1,
    }


def make(tmp_path, lines=()):
    if lines:
        path = tmp_path / AUDIT_FILE
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    sent, changes = [], []
    presenter = EdithPresenter(sent.append, tmp_path, now=lambda: NOW)
    presenter.subscribe(lambda: changes.append(True))
    return presenter, sent, changes


def confirmation(tool="filesystem.delete_file", allow_always=True, task_id="t1"):
    return ev.needs_confirmation(task_id, tool, '{"path": "a.md"}', "¿Autoriza?", allow_always)


def test_needs_confirmation_shows_the_banner(tmp_path):
    presenter, _, changes = make(tmp_path)

    presenter.apply(confirmation())

    pending = presenter.pending
    assert (pending.task_id, pending.tool, pending.question, pending.offers_always) == (
        "t1",
        "filesystem.delete_file",
        "¿Autoriza?",
        True,
    )
    assert changes == [True]


@pytest.mark.parametrize(
    ("tool", "allow_always"), [("shell.run", False), ("filesystem.delete_file", True)]
)
def test_offers_always_follows_the_event(tmp_path, tool, allow_always):
    presenter, *_ = make(tmp_path)

    presenter.apply(confirmation(tool, allow_always))

    assert presenter.pending.offers_always is allow_always


@pytest.mark.parametrize(
    ("action", "decision"), [("allow", "allow"), ("deny", "deny"), ("allow_always", "always")]
)
def test_buttons_send_confirm_and_clear_the_banner(tmp_path, action, decision):
    presenter, sent, _ = make(tmp_path)
    presenter.apply(confirmation())

    getattr(presenter, action)()

    assert sent == [{"type": "confirm", "task_id": "t1", "decision": decision}]
    assert presenter.pending is None


def test_always_is_ignored_when_not_offered(tmp_path):
    presenter, sent, _ = make(tmp_path)
    presenter.apply(confirmation("shell.run", allow_always=False))

    presenter.allow_always()

    assert sent == []
    assert presenter.pending is not None


@pytest.mark.parametrize("action", ["allow", "deny", "allow_always"])
def test_buttons_without_a_banner_send_nothing(tmp_path, action):
    presenter, sent, _ = make(tmp_path)

    getattr(presenter, action)()

    assert sent == []


def task_result(task_id):
    return ev.task_result(
        task_id,
        "viernes",
        "cancelled",
        TaskResult(resumen=""),
        input_tokens=0,
        output_tokens=0,
        elapsed_ms=0,
    )


def test_task_end_clears_its_banner(tmp_path):
    presenter, *_ = make(tmp_path)
    presenter.apply(confirmation(task_id="t1"))

    presenter.apply(task_result("t2"))
    assert presenter.pending is not None

    presenter.apply(task_result("t1"))
    assert presenter.pending is None


def test_initial_audit_load_keeps_only_today_local_date(tmp_path):
    lines = [
        audit_line("2026-10-31T22:59:59Z", "allow"),
        audit_line("2026-10-31T23:00:00Z", "deny", "shell.run"),
        audit_line("2026-11-01T10:30:00Z", "confirm", "filesystem.delete_file", "allow"),
        audit_line("2026-11-01T23:00:00Z", "allow"),
    ]
    presenter, *_ = make(tmp_path, lines)

    presenter.load_audit()

    assert [(r.time, r.tool, r.verdict, r.rule, r.user_decision) for r in presenter.rows] == [
        ("00:00:00", "shell.run", "deny", "r/deny", None),
        ("11:30:00", "filesystem.delete_file", "confirm", "r/confirm", "allow"),
    ]


def test_missing_audit_file_loads_nothing(tmp_path):
    presenter, *_ = make(tmp_path)

    presenter.load_audit()

    assert presenter.rows == []


def test_tool_call_events_are_appended(tmp_path):
    presenter, _, changes = make(tmp_path)
    clock = lambda: datetime(2026, 11, 1, 11, 5, 7, tzinfo=UTC)  # noqa: E731

    presenter.apply(
        ev.tool_call(
            "t1", "viernes", "shell.run", "{}", Ruling(verdict="deny", rule="r/deny"), clock=clock
        )
    )

    [row] = presenter.rows
    assert (row.time, row.agent, row.tool, row.verdict, row.rule, row.user_decision) == (
        "12:05:07",
        "viernes",
        "shell.run",
        "deny",
        "r/deny",
        None,
    )
    assert changes == [True]


@pytest.mark.parametrize(
    ("verdict", "tools"),
    [
        (None, ["a", "b", "c"]),
        ("allow", ["a"]),
        ("confirm", ["c"]),
        ("deny", ["b"]),
    ],
)
def test_verdict_filter(tmp_path, verdict, tools):
    lines = [
        audit_line("2026-11-01T09:00:00Z", "allow", "a"),
        audit_line("2026-11-01T09:00:01Z", "deny", "b"),
        audit_line("2026-11-01T09:00:02Z", "confirm", "c"),
    ]
    presenter, _, changes = make(tmp_path, lines)
    presenter.load_audit()

    presenter.set_filter(verdict)

    assert [row.tool for row in presenter.rows] == tools
    assert presenter.verdict_filter == verdict


def test_unrelated_events_change_nothing(tmp_path):
    presenter, _, changes = make(tmp_path)

    presenter.apply(ev.token("jarvis", "x"))

    assert changes == []
