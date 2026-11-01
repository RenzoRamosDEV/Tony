import json

import pytest

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final, Hang
from tests.fakes.processes import processes_mentioning
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.runner import NotWorkerError, RunDeps, run_task

TASK_ID = "f" * 32
REQUEST = TaskRequest(objetivo="Lista mis notas")
OK = {"resumen": "ok", "datos": None, "pasos": [], "errores": []}


def deps_for(home, engine, **overrides):
    return RunDeps(
        root=home, engine=engine, environ={}, task_id_factory=lambda: TASK_ID, **overrides
    )


def read_log(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_non_worker_agent_is_rejected(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    agent_md = home / "agents" / "viernes" / "agent.md"
    agent_md.write_text(agent_md.read_text().replace("role: worker", "role: front"))
    engine = FakeModelEngine([Final(structured=OK)])

    with pytest.raises(NotWorkerError, match="viernes.*not a worker"):
        await run_task("viernes", REQUEST, deps_for(home, engine))

    assert engine.request is None
    assert not (home / "logs" / "tasks").exists()


async def test_task_timeout_returns_error_and_closes_servers(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    engine = FakeModelEngine([CallTool("filesystem.list_directory", {}), Hang()])

    result = await run_task("viernes", REQUEST, deps_for(home, engine, task_timeout=1.0))

    assert result.errores == ["task timed out after 1 s"]
    assert result.resumen == ""
    events = read_log(home)
    assert events[-1]["type"] == "task_finished" and events[-1]["outcome"] == "timeout"
    assert processes_mentioning(str(notes)) == []


async def test_mcp_down_at_start_keeps_running_with_other_tools(tmp_path, capsys):
    home, _ = make_viernes_home(tmp_path, {"broken": {"command": "/nonexistent/tony-broken"}})
    engine = FakeModelEngine([CallTool("filesystem.list_directory", {}), Final(structured=OK)])

    result = await run_task("viernes", REQUEST, deps_for(home, engine))

    assert result.errores == []
    assert engine.replies[0].text == "a.md"
    events = read_log(home)
    errors = [event for event in events if event["type"] == "error"]
    assert len(errors) == 1 and "broken" in errors[0]["message"]
    assert events[-1]["outcome"] == "ok"
    assert "broken" in capsys.readouterr().err


async def test_engine_failure_becomes_error_result(tmp_path):
    class FailingEngine:
        async def run(self, spec, request, tools, model_id):
            raise RuntimeError("cli crashed")

    home, _ = make_viernes_home(tmp_path)

    result = await run_task("viernes", REQUEST, deps_for(home, FailingEngine()))

    assert result.errores == ["cli crashed"]
    events = read_log(home)
    assert [event["type"] for event in events[-2:]] == ["error", "task_finished"]
    assert events[-2]["source"] == "engine" and events[-2]["message"] == "cli crashed"
    assert events[-1]["outcome"] == "error"


async def test_result_never_contains_resolved_secret(tmp_path):
    home, _ = make_viernes_home(
        tmp_path, {"extra": {"command": "/nonexistent/x", "env": {"T": "${TOKEN}"}}}
    )
    leak = {"resumen": "token s3cr3t", "datos": {"k": "s3cr3t"}, "pasos": [], "errores": []}
    engine = FakeModelEngine([Final(structured=leak)])
    deps = deps_for(home, engine)
    deps.environ = {"TOKEN": "s3cr3t"}

    result = await run_task("viernes", REQUEST, deps)

    assert (result.resumen, result.datos) == ("token ***", {"k": "***"})
    assert "s3cr3t" not in (home / "logs" / "tasks" / f"{TASK_ID}.jsonl").read_text()
