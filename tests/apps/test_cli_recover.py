import json
import os
import re
import time

import pytest
from typer.testing import CliRunner

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.apps.cli.main import create_app
from tony.core.config.placeholders import SecretMasker
from tony.core.memory.actions import ActionJournal
from tony.core.memory.undo import UndoStore

OK = {"resumen": "Hecho.", "datos": None, "pasos": [], "errores": []}
OLD = "a" * 32
OTHER = "b" * 32
CONFIRM_ALL = "default: confirm\nrules: []\n"


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def world(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    return home, notes


def write_log(home, task_id, outcome, *, contexto="ctx", objetivo="Borra a.md"):
    path = home / "logs" / "tasks" / f"{task_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    task = {"objetivo": objetivo, "contexto": contexto, "restricciones": []}
    events = [
        {
            "type": "task_started",
            "ts": "2026-11-01T08:00:00+00:00",
            "agent": "viernes",
            "task": task,
        }
    ]
    if outcome:
        events.append({"type": "task_finished", "outcome": outcome})
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    old = time.time() - 7200
    os.utime(path, (old, old))


def seed_action(home, task_id, tool, *, pre_image_of=None, content="nuevo", state="succeeded"):
    journal = ActionJournal(home, SecretMasker())
    call_id = journal.prepared(task_id, "viernes", tool, "d")
    store = UndoStore(home)
    args = {"path": str(pre_image_of), "content": content} if pre_image_of else {}
    if pre_image_of:
        store.keep(call_id, tool, args)
    detail = store.written_digest(tool, args) if pre_image_of else ""
    journal.transition(call_id, state, detail)
    journal.close()
    return call_id


def invoke(home, *args, steps=None, answer="s\n"):
    engine = FakeModelEngine(steps if steps is not None else [Final(structured=OK)])
    app = create_app(engine_factory=lambda: engine, readline_factory=lambda: lambda: answer)
    result = CliRunner().invoke(app, ["recover", *args], env={"TONY_HOME": str(home)})
    return result, engine


def test_list_with_nothing_to_recover(world):
    result, _ = invoke(world[0], "list")

    assert result.exit_code == 0
    assert result.stdout.strip() == "no tasks to recover"


def test_list_shows_recoverable_tasks_and_labelled_actions(world):
    home, notes = world
    write_log(home, OLD, "cancelled")
    write_log(home, OTHER, "ok")
    (notes / "a.md").write_text("antes")
    undoable = seed_action(home, OLD, "filesystem.write_file", pre_image_of=notes / "a.md")
    plain = seed_action(home, OLD, "shell.run")
    seed_action(home, OLD, "shell.run", state="failed")

    result, _ = invoke(home, "list")

    assert result.exit_code == 0
    assert OLD in result.stdout and OTHER not in result.stdout
    header = result.stdout.splitlines()[0].split()
    assert header == ["task", "agent", "outcome", "started", "objetivo"]
    assert re.search(rf"{undoable}\s+filesystem\.write_file\s+undoable\b", result.stdout)
    assert re.search(rf"{plain}\s+shell\.run\s+not undoable", result.stdout)
    assert result.stdout.count("shell.run") == 1


def test_write_without_pre_image_is_not_undoable(world):
    home, notes = world
    write_log(home, OLD, "timeout")
    call_id = seed_action(home, OLD, "filesystem.write_file")

    result, _ = invoke(home, "list")

    assert re.search(rf"{call_id}\s+filesystem\.write_file\s+not undoable", result.stdout)


def test_list_limit_and_validation(world):
    home, _ = world
    write_log(home, OLD, "cancelled")
    write_log(home, OTHER, "timeout")
    os.utime(home / "logs" / "tasks" / f"{OTHER}.jsonl", (time.time() - 100,) * 2)

    limited, _ = invoke(home, "list", "--limit", "1")
    invalid, _ = invoke(home, "list", "--limit", "0")

    assert OTHER in limited.stdout and OLD not in limited.stdout
    assert invalid.exit_code == 2


def test_resume_runs_a_new_task_with_the_note(world):
    home, _ = world
    write_log(home, OLD, "cancelled", contexto="ctx original")
    call_id = seed_action(home, OLD, "shell.run")

    result, engine = invoke(home, "resume", OLD)

    assert result.exit_code == 0
    assert call_id in engine.request.contexto
    assert engine.request.contexto.endswith("ctx original")
    new_logs = [p for p in (home / "logs" / "tasks").glob("*.jsonl") if p.stem != OLD]
    assert len(new_logs) == 1
    first = json.loads(new_logs[0].read_text().splitlines()[0])
    assert first["resumed_from"] == OLD
    assert new_logs[0].stem != OLD
    assert first["task"]["objetivo"] == "Borra a.md"


def test_resume_without_actions_keeps_the_context(world):
    home, _ = world
    write_log(home, OLD, "timeout", contexto="solo esto")

    _, engine = invoke(home, "resume", OLD)

    assert engine.request.contexto == "solo esto"


def test_resumed_task_still_asks_for_confirmation(world):
    home, notes = world
    write_log(home, OLD, "cancelled")
    steps = [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"}), Final(structured=OK)]

    invoke(home, "resume", OLD, steps=steps, answer="n\n")

    assert (notes / "a.md").exists()


@pytest.mark.parametrize("task_id", ["c" * 32, "../x", "ZZ"])
def test_resume_unknown_task(world, task_id):
    result, engine = invoke(world[0], "resume", task_id)

    assert result.exit_code == 2
    assert f"tony: unknown task {task_id}" in result.output
    assert engine.request is None


def test_resume_finished_task_is_refused(world):
    home, _ = world
    write_log(home, OLD, "ok")

    result, engine = invoke(home, "resume", OLD)

    assert result.exit_code == 2
    assert f"tony: task {OLD} is not recoverable" in result.output
    assert engine.request is None


def do_write(home, notes, new="nuevo"):
    """A journaled write over a.md done as the proxy does, returning its call id."""
    target = notes / "a.md"
    journal = ActionJournal(home, SecretMasker())
    store = UndoStore(home)
    args = {"path": str(target), "content": new}
    call_id = journal.prepared("t1", "viernes", "filesystem.write_file", "d")
    store.keep(call_id, "filesystem.write_file", args)
    target.write_text(new)
    journal.transition(call_id, "succeeded", store.written_digest("filesystem.write_file", args))
    journal.close()
    return call_id


def test_undo_restores_the_previous_content_through_the_guard(tmp_path):
    home, notes = make_viernes_home(tmp_path, policy=CONFIRM_ALL)
    call_id = do_write(home, notes)

    result, _ = invoke(home, "undo", call_id, answer="s\n")

    assert result.exit_code == 0
    assert (notes / "a.md").read_text() == "# Nota A\nComprar pan."
    assert any(
        json.loads(line)["tool"] == "filesystem.write_file"
        for log in (home / "logs" / "audit.jsonl",)
        for line in log.read_text().splitlines()
    )


def test_undo_denied_by_the_user_writes_nothing(tmp_path):
    home, notes = make_viernes_home(tmp_path, policy=CONFIRM_ALL)
    call_id = do_write(home, notes)

    result, _ = invoke(home, "undo", call_id, answer="n\n")

    assert result.exit_code != 0
    assert (notes / "a.md").read_text() == "nuevo"


def test_undo_refuses_when_the_file_changed(world):
    home, notes = world
    call_id = do_write(home, notes)
    (notes / "a.md").write_text("editado a mano")

    result, _ = invoke(home, "undo", call_id)

    assert result.exit_code != 0
    assert "file changed since the action" in result.output
    assert (notes / "a.md").read_text() == "editado a mano"


def test_undo_refusals_for_unknown_and_irreversible_calls(world):
    home, _ = world
    write_log(home, OLD, "cancelled")
    shell_call = seed_action(home, OLD, "shell.run")

    unknown, _ = invoke(home, "undo", "00000000-0000-4000-8000-000000000000")
    irreversible, _ = invoke(home, "undo", shell_call)

    assert unknown.exit_code == 2 and "tony: unknown action" in unknown.output
    assert irreversible.exit_code == 2 and "not undoable" in irreversible.output


def test_undo_can_itself_be_undone(world):
    home, notes = world
    call_id = do_write(home, notes)
    invoke(home, "undo", call_id, answer="s\n")

    journal = ActionJournal(home, SecretMasker())
    undo_call = journal.list(limit=1)[0].call_id
    journal.close()

    assert UndoStore(home).is_undoable(undo_call)


def test_resume_rejects_ids_that_climb_out_of_the_logs_directory(world):
    home, _ = world
    write_log(home, OLD, "cancelled")

    result, engine = invoke(home, "resume", f"../tasks/{OLD}")

    assert result.exit_code == 2 and "unknown task" in result.output
    assert engine.request is None
