import json

import pytest

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final, Hang
from tests.fakes.guards import RecordingGuard
from tony.core.config.errors import DefinitionError
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "a" * 32
REQUEST = TaskRequest(objetivo="Lee mis notas")
OK = {"resumen": "ok", "datos": None, "pasos": [], "errores": []}


def deps_for(home, engine, **overrides):
    return RunDeps(
        root=home, engine=engine, environ={}, task_id_factory=lambda: TASK_ID, **overrides
    )


def audit_lines(home):
    path = home / "logs" / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def test_edith_is_the_default_guard(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine(
        [CallTool("filesystem.read_file", {"path": "a.md"}), Final(structured=OK)]
    )

    result = await run_task("viernes", REQUEST, deps_for(home, engine))

    assert result.errores == []
    assert engine.replies[0].text == "# Nota A\nComprar pan."
    [line] = audit_lines(home)
    assert (line["task_id"], line["agent"], line["tool"]) == (
        TASK_ID,
        "viernes",
        "filesystem.read_file",
    )
    assert (line["verdict"], line["rule"], line["user_decision"]) == (
        "allow",
        "filesystem.read_*/allow",
        None,
    )


async def test_guard_comes_from_config(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    (home / "agents" / "edith").rename(home / "agents" / "vigia")
    (home / "agents" / "vigia" / "agent.md").write_text(
        (home / "agents" / "vigia" / "agent.md").read_text().replace("name: edith", "name: vigia")
    )
    (home / "config").mkdir()
    (home / "config" / "tony.yaml").write_text("guard: vigia\n")
    engine = FakeModelEngine(
        [CallTool("filesystem.read_file", {"path": "a.md"}), Final(structured=OK)]
    )

    await run_task("viernes", REQUEST, deps_for(home, engine))

    assert audit_lines(home)[0]["rule"] == "filesystem.read_*/allow"


async def test_injected_guard_overrides_edith(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    guard = RecordingGuard()
    engine = FakeModelEngine(
        [CallTool("filesystem.read_file", {"path": "a.md"}), Final(structured=OK)]
    )

    await run_task("viernes", REQUEST, deps_for(home, engine, guard=guard))

    assert [call.tool for call in guard.calls] == ["filesystem.read_file"]
    assert audit_lines(home) == []


@pytest.mark.parametrize(
    ("policy", "field"),
    [(None, None), ("default: confirm\nlimits: {max_cost: 3}\n", "limits.max_cost")],
)
async def test_invalid_or_missing_policy_fails_before_any_server_connects(tmp_path, policy, field):
    home, _ = make_viernes_home(tmp_path, policy=policy or "")
    if policy is None:
        (home / "agents" / "edith" / "policy.yaml").unlink()
    engine = FakeModelEngine([Final(structured=OK)])

    with pytest.raises(DefinitionError) as info:
        await run_task("viernes", REQUEST, deps_for(home, engine))

    assert (info.value.file, info.value.field) == ("agents/edith/policy.yaml", field)
    assert engine.request is None
    assert not (home / "logs").exists()


async def test_invalid_guard_agent_fails_before_running(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    (home / "agents" / "edith" / "tool").mkdir()
    engine = FakeModelEngine([Final(structured=OK)])

    with pytest.raises(DefinitionError, match="agents/edith/tool/"):
        await run_task("viernes", REQUEST, deps_for(home, engine))

    assert engine.request is None


async def test_task_timeout_from_policy_limits(tmp_path):
    home, _ = make_viernes_home(tmp_path, policy="default: confirm\nlimits: {task_timeout_s: 1}\n")
    engine = FakeModelEngine([Hang()])

    result = await run_task("viernes", REQUEST, deps_for(home, engine))

    assert result.errores == ["task timed out after 1 s"]


async def test_explicit_task_timeout_overrides_policy(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine([Hang()])

    result = await run_task("viernes", REQUEST, deps_for(home, engine, task_timeout=0.2))

    assert result.errores == ["task timed out after 0.2 s"]


def test_task_timeout_defaults_to_the_policy(tmp_path):
    assert RunDeps(root=tmp_path, engine=FakeModelEngine([])).task_timeout is None
