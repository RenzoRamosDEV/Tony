import json
from datetime import UTC, datetime

import pytest

from tests.core.guard.edith_helpers import TickingClock
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.confirm import FakeConfirmer
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.core.events.messages import TaskRequest
from tony.core.mcp.native import NativeTool
from tony.core.orchestrator.runner import NotWorkerError, RunDeps, run_task

TASK_ID = "d" * 32
REQUEST = TaskRequest(objetivo="Haz algo")
OK = {"resumen": "ok", "datos": None, "pasos": [], "errores": []}
FIXED = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)


def deps_for(home, engine, **overrides):
    return RunDeps(
        root=home, engine=engine, environ={}, task_id_factory=lambda: TASK_ID, **overrides
    )


def log_lines(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_engine_receives_the_worker_spec(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine([Final(structured=OK)])

    await run_task("viernes", REQUEST, deps_for(home, engine))

    assert (engine.spec.name, engine.spec.role) == ("viernes", "worker")


async def test_declared_native_tools_are_offered_and_run(tmp_path):
    async def now(args):
        return "2026-11-01T10:00:00Z"

    home, _ = make_viernes_home(tmp_path)
    tool_json = home / "agents" / "viernes" / "tool" / "tool.json"
    tool_json.write_text(json.dumps({**json.loads(tool_json.read_text()), "native": ["now"]}))
    policy = "default: allow\n"
    (home / "agents" / "edith" / "policy.yaml").write_text(policy)
    engine = FakeModelEngine([CallTool("tony.now", {}), Final(structured=OK)])
    native = {"now": NativeTool(description="Hora.", input_schema={}, run=now)}

    await run_task("viernes", REQUEST, deps_for(home, engine, native=native))

    assert engine.replies[0].text == "2026-11-01T10:00:00Z"


async def test_non_worker_error_names_the_role(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    agent_md = home / "agents" / "viernes" / "agent.md"
    agent_md.write_text(agent_md.read_text().replace("role: worker", "role: front"))

    with pytest.raises(NotWorkerError) as info:
        await run_task("viernes", REQUEST, deps_for(home, FakeModelEngine([])))

    assert str(info.value) == "agent 'viernes' is not a worker (role: front)"


async def test_task_log_masks_env_secrets_in_args_and_uses_the_clock(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    (home / "config").mkdir()
    (home / "config" / ".env").write_text("GITHUB_TOKEN=s3cr3t\n")
    engine = FakeModelEngine(
        [CallTool("filesystem.read_file", {"path": "s3cr3t.md"}), Final(structured=OK)]
    )

    await run_task("viernes", REQUEST, deps_for(home, engine, clock=lambda: FIXED))

    lines = log_lines(home)
    call = next(line for line in lines if line["type"] == "tool_call")
    assert call["args"] == {"path": "***.md"}
    assert {line["ts"] for line in lines} == {"2026-11-01T08:30:00+00:00"}


async def test_server_stderr_logged_under_logs_mcp(tmp_path):
    home, _ = make_viernes_home(tmp_path)

    await run_task("viernes", REQUEST, deps_for(home, FakeModelEngine([Final(structured=OK)])))

    assert "fake filesystem server" in (home / "logs" / "mcp" / "filesystem.log").read_text()


async def test_engine_error_without_message_uses_its_type(tmp_path):
    class SilentFailure:
        async def run(self, spec, request, tools, model_id):
            raise RuntimeError()

    home, _ = make_viernes_home(tmp_path)

    result = await run_task("viernes", REQUEST, deps_for(home, SilentFailure()))

    assert result.errores == ["RuntimeError"]


async def test_edith_uses_injected_clocks_for_audit(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    engine = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"}), Final(structured=OK)]
    )
    deps = deps_for(
        home,
        engine,
        confirmer=FakeConfirmer([True]),
        clock=lambda: FIXED,
        monotonic=TickingClock(50.0, 52.5),
    )

    await run_task("viernes", REQUEST, deps)

    [line] = [json.loads(raw) for raw in (home / "logs" / "audit.jsonl").read_text().splitlines()]
    assert (line["ts"], line["duration_ms"]) == ("2026-11-01T08:30:00Z", 2500)
