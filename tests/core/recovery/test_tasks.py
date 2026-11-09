import json
import os
from datetime import UTC, datetime, timedelta

from tony.core.memory.actions import ActionRecord
from tony.core.recovery.tasks import (
    MAX_NOTE_ACTIONS,
    STALE_AFTER_S,
    find_task,
    resume_request,
    scan_tasks,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def tid(n: int) -> str:
    return f"{n:032x}"


def write_log(root, task_id, events, *, age_s=10_000):
    path = root / "logs" / "tasks" / f"{task_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [e if isinstance(e, str) else json.dumps(e) for e in events]
    path.write_text("\n".join(lines) + "\n")
    stamp = (NOW - timedelta(seconds=age_s)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def started(ts="2026-11-01T08:00:00+00:00", agent="viernes", objetivo="haz x", **extra):
    task = {"objetivo": objetivo, "contexto": "ctx", "restricciones": []}
    return {"type": "task_started", "ts": ts, "agent": agent, "task": task, **extra}


def finished(outcome):
    return {"type": "task_finished", "outcome": outcome}


def scan(root, **kwargs):
    return scan_tasks(root, lambda: NOW, **kwargs)


def test_cancelled_and_timeout_are_listed_ok_and_error_are_not(tmp_path):
    for n, outcome in enumerate(["cancelled", "timeout", "ok", "error"]):
        write_log(tmp_path, tid(n), [started(), finished(outcome)])

    found = scan(tmp_path)

    assert {t.task_id: t.outcome for t in found} == {tid(0): "cancelled", tid(1): "timeout"}


def test_listing_carries_agent_request_and_start_time(tmp_path):
    write_log(tmp_path, tid(1), [started(agent="tony", objetivo="o"), finished("cancelled")])

    (task,) = scan(tmp_path)

    assert (task.agent, task.request.objetivo, task.request.contexto) == ("tony", "o", "ctx")
    assert task.started_at == "2026-11-01T08:00:00+00:00"


def test_no_end_event_is_interrupted_only_past_the_stale_age(tmp_path):
    write_log(tmp_path, tid(1), [started()], age_s=STALE_AFTER_S + 1)
    write_log(tmp_path, tid(2), [started()], age_s=STALE_AFTER_S)
    write_log(tmp_path, tid(3), [started()], age_s=STALE_AFTER_S - 1)

    found = scan(tmp_path)

    assert [(t.task_id, t.outcome) for t in found] == [(tid(1), "interrupted")]


def test_malformed_lines_are_skipped_and_logs_without_start_ignored(tmp_path):
    write_log(tmp_path, tid(1), ["{not json", started(), "", finished("timeout")])
    write_log(tmp_path, tid(2), [{"type": "tool_call"}, finished("cancelled")])
    write_log(tmp_path, tid(3), [])

    assert [t.task_id for t in scan(tmp_path)] == [tid(1)]


def test_resumed_originals_are_hidden(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("cancelled")])
    write_log(tmp_path, tid(2), [started(resumed_from=tid(1)), finished("cancelled")])

    assert [t.task_id for t in scan(tmp_path)] == [tid(2)]


def test_newest_first_by_modification_time(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("timeout")], age_s=5000)
    write_log(tmp_path, tid(2), [started(), finished("timeout")], age_s=1000)

    assert [t.task_id for t in scan(tmp_path)] == [tid(2), tid(1)]


def test_only_the_newest_files_are_scanned(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("timeout")], age_s=5000)
    write_log(tmp_path, tid(2), [started(), finished("timeout")], age_s=1000)

    assert [t.task_id for t in scan(tmp_path, limit_files=1)] == [tid(2)]


def test_no_logs_directory_yields_nothing(tmp_path):
    assert scan(tmp_path) == []


def test_find_task_returns_none_for_unknown_and_any_outcome_for_known(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("ok")])

    assert find_task(tmp_path, tid(2), lambda: NOW) is None
    task = find_task(tmp_path, tid(1), lambda: NOW)
    assert task.outcome == "ok" and not task.recoverable


def action(n, tool="filesystem.write_file"):
    stamp = f"2026-11-01T08:0{n}:00+00:00"
    return ActionRecord(f"call-{n}", "t", "viernes", tool, "d", "succeeded", stamp, stamp, "")


def test_resume_without_actions_keeps_the_request(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("cancelled")])
    (task,) = scan(tmp_path)

    assert resume_request(task, []) == task.request


def test_resume_note_lists_actions_then_original_context(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("cancelled")])
    (task,) = scan(tmp_path)

    request = resume_request(task, [action(1), action(2, "shell.run")])

    lines = request.contexto.splitlines()
    assert lines[0] == "Acciones ya completadas en un intento anterior (no las repitas):"
    assert lines[1] == "- filesystem.write_file (2026-11-01T08:01:00+00:00, llamada call-1)"
    assert lines[2] == "- shell.run (2026-11-01T08:02:00+00:00, llamada call-2)"
    assert lines[3] == "(Los argumentos de esas llamadas no se conservan.)"
    assert lines[4] == ""
    assert lines[5] == "ctx"
    assert request.objetivo == task.request.objetivo


def test_resume_note_is_capped(tmp_path):
    write_log(tmp_path, tid(1), [started(), finished("cancelled")])
    (task,) = scan(tmp_path)

    request = resume_request(task, [action(i % 10) for i in range(MAX_NOTE_ACTIONS + 5)])

    assert request.contexto.count("\n- ") == MAX_NOTE_ACTIONS
