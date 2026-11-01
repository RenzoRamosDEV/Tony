"""Offline acceptance: Viernes with the fake engine and servers under the shipped policy."""

import json

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.confirm import HANG, FakeConfirmer
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.processes import processes_mentioning
from tests.fakes.servers import fake_shell_entry
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.orchestrator.ports import Usage
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "c" * 32
REQUEST = TaskRequest(objetivo="Ordena mis notas")
OK = {"resumen": "hecho", "datos": None, "pasos": [], "errores": []}
DELETE_RULE = "filesystem.delete*/confirm"


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


async def run(home, steps, confirmer=None):
    engine = FakeModelEngine([*steps, Final(structured=OK)])
    deps = RunDeps(
        root=home,
        engine=engine,
        environ={},
        confirmer=confirmer or FakeConfirmer(),
        task_id_factory=lambda: TASK_ID,
    )
    result = await run_task("viernes", REQUEST, deps)
    return result, engine


def audit(home):
    path = home / "logs" / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def events(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_write_inside_notes_is_allowed_and_audited_once(tmp_path):
    home, notes = make_viernes_home(tmp_path)

    result, _ = await run(
        home, [CallTool("filesystem.write_file", {"path": f"{notes}/b.md", "content": "hola"})]
    )

    assert result.errores == []
    assert (notes / "b.md").read_text() == "hola"
    [line] = audit(home)
    assert (line["verdict"], line["rule"], line["user_decision"]) == (
        "allow",
        "filesystem.write_file/allow",
        None,
    )


async def test_confirmed_delete_runs(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    confirmer = FakeConfirmer([True])

    result, engine = await run(
        home, [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"})], confirmer
    )

    assert result.errores == []
    assert engine.replies[0].text == f"deleted {notes}/a.md"
    assert not (notes / "a.md").exists()
    assert confirmer.questions == [
        f'Acción: filesystem.delete_file {{"path": "{notes}/a.md"}}. '
        f"Regla: {DELETE_RULE}. ¿Autoriza?"
    ]
    assert audit(home)[0]["user_decision"] == "allow"


async def test_rejected_delete_cancels_the_task(tmp_path):
    home, notes = make_viernes_home(tmp_path)

    result, _ = await run(
        home,
        [
            CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"}),
            CallTool("filesystem.write_file", {"path": f"{notes}/later.md", "content": "x"}),
        ],
        FakeConfirmer([False]),
    )

    assert result == TaskResult(
        resumen="",
        errores=[
            f"tarea cancelada: el usuario no autorizó filesystem.delete_file (regla {DELETE_RULE})"
        ],
    )
    assert (notes / "a.md").exists()
    assert not (notes / "later.md").exists()
    assert audit(home)[0]["user_decision"] == "deny"
    log = events(home)
    assert (log[-1]["type"], log[-1]["outcome"]) == ("task_finished", "cancelled")
    assert processes_mentioning(str(notes)) == []


async def test_confirmation_timeout_cancels_and_is_audited(tmp_path):
    policy = SHIPPED_POLICY_YAML.replace("confirm_timeout_s: 60", "confirm_timeout_s: 0.1")
    home, notes = make_viernes_home(tmp_path, policy=policy)

    result, _ = await run(
        home,
        [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"})],
        FakeConfirmer([HANG]),
    )

    assert result.errores == [
        "tarea cancelada: sin respuesta a la confirmación de filesystem.delete_file "
        f"en 0.1 s (regla {DELETE_RULE})"
    ]
    [line] = audit(home)
    assert (line["verdict"], line["user_decision"]) == ("confirm", "timeout")
    assert (notes / "a.md").exists()


async def test_third_denied_shell_run_cancels(tmp_path):
    home, _ = make_viernes_home(tmp_path, {"shell": fake_shell_entry()})
    sudo = CallTool("shell.run", {"command": "sudo dnf update"})

    result, engine = await run(home, [sudo, sudo, sudo])

    assert result.errores == [
        "tarea cancelada: shell.run bloqueada 3 veces por la política (regla shell.run/deny)"
    ]
    blocked = '{"error": "blocked_by_policy", "rule": "shell.run/deny"}'
    assert [reply.text for reply in engine.replies] == [blocked, blocked, blocked]
    assert [line["verdict"] for line in audit(home)] == ["deny", "deny", "deny"]
    assert events(home)[-1]["outcome"] == "cancelled"


async def test_two_denials_do_not_cancel(tmp_path):
    home, _ = make_viernes_home(tmp_path, {"shell": fake_shell_entry()})
    sudo = CallTool("shell.run", {"command": "sudo dnf update"})

    result, _ = await run(home, [sudo, sudo])

    assert result.errores == []
    assert events(home)[-1]["outcome"] == "ok"


async def test_default_deny_blocks_unknown_tool(tmp_path):
    home, _ = make_viernes_home(tmp_path, {"foo": fake_shell_entry()}, policy="default: deny\n")

    result, engine = await run(home, [CallTool("foo.bar", {})])

    assert result.errores == []
    assert engine.replies[0].text == '{"error": "blocked_by_policy", "rule": "default"}'
    [line] = audit(home)
    assert (line["verdict"], line["rule"], line["user_decision"]) == ("deny", "default", None)


@pytest.mark.parametrize(("usage", "alerts"), [(Usage(50000, 1), 1), (Usage(49999, 1), 0)])
async def test_token_alert_logged_once_above_threshold(tmp_path, usage, alerts):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine([Final(structured=OK, usage=usage)])
    deps = RunDeps(root=home, engine=engine, environ={}, task_id_factory=lambda: TASK_ID)

    result = await run_task("viernes", REQUEST, deps)

    assert result.errores == []
    found = [event for event in events(home) if event["type"] == "token_alert"]
    assert [(event["total_tokens"], event["limit"]) for event in found] == [(50001, 50000)][:alerts]
    assert events(home)[-1]["outcome"] == "ok"
