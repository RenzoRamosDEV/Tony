import json

from tony.core.events import log_events
from tony.core.events.messages import TaskRequest, TaskResult


def roundtrip(event):
    return json.loads(json.dumps(event))


def test_task_started():
    event = log_events.task_started("viernes", TaskRequest(objetivo="o"))

    assert roundtrip(event) == {
        "type": "task_started",
        "agent": "viernes",
        "task": {"objetivo": "o", "contexto": "", "restricciones": []},
    }


def test_tool_call():
    event = log_events.tool_call("filesystem.read_file", {"path": "a.md"})

    assert roundtrip(event) == {
        "type": "tool_call",
        "tool": "filesystem.read_file",
        "args": {"path": "a.md"},
    }


def test_tool_result():
    event = log_events.tool_result("filesystem.read_file", ok=False, content="boom")

    assert roundtrip(event) == {
        "type": "tool_result",
        "tool": "filesystem.read_file",
        "ok": False,
        "content": "boom",
    }


def test_token_usage():
    event = log_events.token_usage(input_tokens=12, output_tokens=3)

    assert roundtrip(event) == {"type": "token_usage", "input_tokens": 12, "output_tokens": 3}


def test_task_finished():
    result = TaskResult(resumen="r", datos={"a": [1]}, pasos=["p"], errores=[])

    event = log_events.task_finished("ok", result)

    assert roundtrip(event) == {
        "type": "task_finished",
        "outcome": "ok",
        "result": {"resumen": "r", "datos": {"a": [1]}, "pasos": ["p"], "errores": []},
    }


def test_error():
    event = log_events.error("mcp.github", "connection refused")

    assert roundtrip(event) == {
        "type": "error",
        "source": "mcp.github",
        "message": "connection refused",
    }
