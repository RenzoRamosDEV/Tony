import json
from datetime import UTC, datetime

import pytest

from tests.core.orchestrator.skills_home import set_native, write_subagent
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import ByAgentEngine, CallTool, Final, Hang, Raise
from tests.fakes.processes import processes_mentioning
from tests.fakes.servers import fake_fs_entry
from tony.apps.desktop.presenters.activity import ActivityPresenter
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.ports import Usage
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "a" * 32
REQUEST = TaskRequest(objetivo="Resume la nota a.md")
SUB_RESULT = {
    "resumen": "Comprar pan.",
    "datos": {"lineas": 2},
    "pasos": ["leí a.md"],
    "errores": [],
}
FIXED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
CALL_SUB = CallTool(
    "tony.run_subagent", {"name": "resumidor", "tarea": {"objetivo": "Resume a.md"}}
)
READ = CallTool("filesystem.read_file", {"path": "a.md"})


def echo_reply(replies):
    return {"resumen": replies[0].text, "errores": []}


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def make_home(tmp_path, policy=None, sub_role=None):
    home, notes = make_viernes_home(tmp_path, policy=policy)
    set_native(home, "viernes", ["read_skill", "run_subagent"])
    folder = write_subagent(home, "resumidor", servers={"filesystem": fake_fs_entry(str(notes))})
    if sub_role:
        md = folder / "agent.md"
        md.write_text(md.read_text().replace("role: worker", f"role: {sub_role}"))
    return home, notes


async def run(home, scripts, published=None):
    engine = ByAgentEngine(scripts)
    published = [] if published is None else published
    deps = RunDeps(
        root=home,
        engine=engine,
        environ={},
        task_id_factory=lambda: TASK_ID,
        clock=lambda: FIXED,
        publish=published.append,
    )
    result = await run_task("viernes", REQUEST, deps)
    return engine, result


def log_lines(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def audit_lines(home):
    path = home / "logs" / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def sub_reply(engine):
    return engine.engines["viernes"].replies[0]


async def test_subagent_result_returned_audited_logged_and_published(tmp_path):
    home, notes = make_home(tmp_path)
    published = []

    engine, result = await run(
        home,
        {
            "viernes": [CALL_SUB, Final(structured=echo_reply, usage=Usage(10, 5))],
            "resumidor": [READ, Final(structured=SUB_RESULT, usage=Usage(4, 2))],
        },
        published,
    )

    reply = sub_reply(engine)
    assert (json.loads(reply.text), reply.is_error) == (SUB_RESULT, False)
    assert result.resumen == reply.text
    assert [
        (line["agent"], line["tool"], line["rule"], line["task_id"]) for line in audit_lines(home)
    ] == [
        ("viernes", "tony.run_subagent", "tony.read_skill/allow", TASK_ID),
        ("viernes/resumidor", "filesystem.read_file", "filesystem.read_*/allow", TASK_ID),
    ]
    nested = [
        (line["type"], line["agent"], line.get("tool"), line.get("outcome"))
        for line in log_lines(home)
        if line["type"] in {"tool_call", "tool_result", "subagent_started", "subagent_finished"}
    ]
    assert nested == [
        ("tool_call", "viernes", "tony.run_subagent", None),
        ("subagent_started", "viernes/resumidor", None, None),
        ("tool_call", "viernes/resumidor", "filesystem.read_file", None),
        ("tool_result", "viernes/resumidor", "filesystem.read_file", None),
        ("subagent_finished", "viernes/resumidor", None, "ok"),
        ("tool_result", "viernes", "tony.run_subagent", None),
    ]
    assert len(list((home / "logs" / "tasks").iterdir())) == 1
    usage = [
        (line["input_tokens"], line["output_tokens"])
        for line in log_lines(home)
        if line["type"] == "token_usage"
    ]
    assert sorted(usage) == [(4, 2), (10, 5)]
    calls = [event for event in published if event["type"] == "tool_call"]
    assert [(event["task_id"], event["agent"], event["tool"]) for event in calls] == [
        (TASK_ID, "viernes", "tony.run_subagent"),
        (TASK_ID, "viernes/resumidor", "filesystem.read_file"),
    ]
    assert ("viernes/resumidor", "filesystem", True) in [
        (event["agent"], event["server"], event["up"])
        for event in published
        if event["type"] == "mcp_status"
    ]
    assert [event["type"] for event in published].count("task_started") == 1
    [task_result] = [event for event in published if event["type"] == "result"]
    assert (task_result["input_tokens"], task_result["output_tokens"]) == (14, 7)
    assert processes_mentioning(str(notes)) == []
    presenter = ActivityPresenter()
    for event in published:
        presenter.apply(event)
    [task] = presenter.tasks
    assert [(sub.name, [call.tool for call in sub.calls]) for sub in task.subagents] == [
        ("resumidor", ["filesystem.read_file"])
    ]


async def test_unknown_subagent_lists_available(tmp_path):
    home, _ = make_home(tmp_path)
    call = CallTool("tony.run_subagent", {"name": "traductor", "tarea": {"objetivo": "x"}})

    engine, result = await run(home, {"viernes": [call, Final(structured=echo_reply)]})

    reply = sub_reply(engine)
    assert (reply.text, reply.is_error) == (
        "subagent 'traductor' not found; available: resumidor",
        True,
    )
    assert engine.calls == ["viernes"] and result.errores == []


@pytest.mark.parametrize("name", ["../viernes", "resumidor/..", ""])
async def test_traversal_names_not_found(tmp_path, name):
    home, _ = make_home(tmp_path)
    call = CallTool("tony.run_subagent", {"name": name, "tarea": {"objetivo": "x"}})

    engine, _ = await run(home, {"viernes": [call, Final(structured=echo_reply)]})

    assert sub_reply(engine).text.startswith(f"subagent '{name}' not found")


@pytest.mark.parametrize("tarea", [{"objetivo": ""}, {}, "texto"])
async def test_invalid_task_runs_no_subagent(tmp_path, tarea):
    home, _ = make_home(tmp_path)
    call = CallTool("tony.run_subagent", {"name": "resumidor", "tarea": tarea})

    engine, _ = await run(home, {"viernes": [call, Final(structured=echo_reply)]})

    reply = sub_reply(engine)
    assert reply.is_error and "objetivo" in reply.text
    assert engine.calls == ["viernes"]


async def test_invalid_subagent_names_file_and_field(tmp_path):
    home, _ = make_home(tmp_path, sub_role="front")

    engine, _ = await run(home, {"viernes": [CALL_SUB, Final(structured=echo_reply)]})

    reply = sub_reply(engine)
    assert reply.is_error
    assert "agents/viernes/subagents/resumidor/agent.md" in reply.text and "role" in reply.text


async def test_subagent_engine_error_is_returned_and_parent_continues(tmp_path):
    home, _ = make_home(tmp_path)

    engine, result = await run(
        home,
        {
            "viernes": [CALL_SUB, Final(structured={"resumen": "seguí"})],
            "resumidor": [Raise(RuntimeError("model down"))],
        },
    )

    reply = sub_reply(engine)
    assert reply.is_error and json.loads(reply.text)["errores"] == ["model down"]
    finished = [line for line in log_lines(home) if line["type"] == "subagent_finished"]
    assert [line["outcome"] for line in finished] == ["error"]
    assert result.resumen == "seguí"


async def test_repeated_denials_inside_subagent_cancel_parent(tmp_path):
    policy = (
        "default: allow\n"
        "rules:\n  - match: filesystem.read_*\n    verdict: deny\n"
        "limits: {max_denied_retries: 2}\n"
    )
    home, notes = make_home(tmp_path, policy=policy)

    _, result = await run(
        home,
        {
            "viernes": [CALL_SUB, Final(structured={"resumen": "no"})],
            "resumidor": [READ, READ, READ, Final(structured=SUB_RESULT)],
        },
    )

    assert result.errores and "filesystem.read_file" in result.errores[0]
    assert log_lines(home)[-1]["outcome"] == "cancelled"
    assert processes_mentioning(str(notes)) == []


async def test_parent_timeout_stops_hanging_subagent(tmp_path):
    home, notes = make_home(tmp_path, policy="default: allow\nlimits: {task_timeout_s: 1}\n")

    _, result = await run(
        home,
        {"viernes": [CALL_SUB, Final(structured={"resumen": "no"})], "resumidor": [READ, Hang()]},
    )

    assert log_lines(home)[-1]["outcome"] == "timeout"
    assert "timed out" in result.errores[0]
    assert processes_mentioning(str(notes)) == []


async def test_subagent_longer_than_tool_timeout_succeeds(tmp_path):
    home, _ = make_home(tmp_path, policy="default: allow\nlimits: {tool_timeout_s: 0.2}\n")
    nap = CallTool("filesystem.sleep", {"seconds": 0.15})

    engine, _ = await run(
        home,
        {
            "viernes": [CALL_SUB, Final(structured=echo_reply)],
            "resumidor": [nap, nap, Final(structured=SUB_RESULT)],
        },
    )

    reply = sub_reply(engine)
    assert (reply.is_error, json.loads(reply.text)) == (False, SUB_RESULT)
