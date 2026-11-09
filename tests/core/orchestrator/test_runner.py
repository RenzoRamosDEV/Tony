import json

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.orchestrator.ports import Usage
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "0" * 32
REQUEST = TaskRequest(objetivo="Resume las notas de la carpeta")


def summarize(replies):
    return {
        "resumen": "Una nota sobre la compra.",
        "datos": {"a.md": replies[1].text},
        "pasos": ["filesystem.list_directory", "filesystem.read_file"],
        "errores": [],
    }


def read_log(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_viernes_uses_two_tools_offline(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine(
        [
            CallTool("filesystem.list_directory", {"path": "."}),
            CallTool("filesystem.read_file", {"path": "a.md"}),
            Final(structured=summarize, usage=Usage(200, 40, 900, 100, 0.012)),
        ]
    )
    deps = RunDeps(root=home, engine=engine, environ={}, task_id_factory=lambda: TASK_ID)

    result = await run_task("viernes", REQUEST, deps)

    assert [reply.text for reply in engine.replies] == ["a.md", "# Nota A\nComprar pan."]
    assert result == TaskResult(**summarize(engine.replies))
    assert engine.model_id == "claude-sonnet-5-5"
    assert engine.request == REQUEST
    assert "filesystem.read_file" in engine.offered
    events = read_log(home)
    assert [event["type"] for event in events] == [
        "task_started",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "token_usage",
        "task_finished",
    ]
    assert events[0]["agent"] == "viernes" and events[0]["task"] == REQUEST.model_dump()
    assert [event["tool"] for event in events if event["type"] == "tool_call"] == [
        "filesystem.list_directory",
        "filesystem.read_file",
    ]
    assert events[5] | {"ts": None} == {
        "ts": None,
        "task_id": TASK_ID,
        "type": "token_usage",
        "input_tokens": 200,
        "output_tokens": 40,
        "cache_read_tokens": 900,
        "cache_creation_tokens": 100,
        "cost_usd": 0.012,
    }
    assert events[-1]["outcome"] == "ok"
    assert events[-1]["result"] == result.model_dump(mode="json")


async def test_unstructured_answer_reports_error(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine([Final(text="no sé")])
    deps = RunDeps(root=home, engine=engine, environ={}, task_id_factory=lambda: TASK_ID)

    result = await run_task("viernes", REQUEST, deps)

    assert result == TaskResult(resumen="no sé", errores=["respuesta no estructurada"])
    assert read_log(home)[-1]["outcome"] == "error"
