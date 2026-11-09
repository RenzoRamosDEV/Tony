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
    event = log_events.tool_call("viernes", "filesystem.read_file", {"path": "a.md"})

    assert roundtrip(event) == {
        "type": "tool_call",
        "agent": "viernes",
        "tool": "filesystem.read_file",
        "args": {"path": "a.md"},
    }


def test_tool_result():
    event = log_events.tool_result(
        "viernes/resumidor", "filesystem.read_file", ok=False, content="boom"
    )

    assert roundtrip(event) == {
        "type": "tool_result",
        "agent": "viernes/resumidor",
        "tool": "filesystem.read_file",
        "ok": False,
        "content": "boom",
    }


def test_token_usage():
    event = log_events.token_usage(input_tokens=12, output_tokens=3)

    assert (
        roundtrip(event).items()
        >= {
            "type": "token_usage",
            "input_tokens": 12,
            "output_tokens": 3,
        }.items()
    )


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


def test_token_alert():
    event = log_events.token_alert(total_tokens=50001, limit=50000)

    assert roundtrip(event) == {"type": "token_alert", "total_tokens": 50001, "limit": 50000}


def test_task_finished_cancelled():
    result = TaskResult(resumen="", errores=["tarea cancelada: x"])

    event = log_events.task_finished("cancelled", result)

    assert roundtrip(event) == {
        "type": "task_finished",
        "outcome": "cancelled",
        "result": {"resumen": "", "datos": None, "pasos": [], "errores": ["tarea cancelada: x"]},
    }


def test_subagent_started():
    event = log_events.subagent_started("viernes/resumidor", TaskRequest(objetivo="o"))

    assert roundtrip(event) == {
        "type": "subagent_started",
        "agent": "viernes/resumidor",
        "task": {"objetivo": "o", "contexto": "", "restricciones": []},
    }


def test_subagent_finished():
    result = TaskResult(resumen="r", errores=[])

    event = log_events.subagent_finished("viernes/resumidor", "ok", result)

    assert roundtrip(event) == {
        "type": "subagent_finished",
        "agent": "viernes/resumidor",
        "outcome": "ok",
        "result": {"resumen": "r", "datos": None, "pasos": [], "errores": []},
    }


def test_token_usage_carries_cache_and_cost():
    event = log_events.token_usage(
        input_tokens=12,
        output_tokens=3,
        cache_read_tokens=900,
        cache_creation_tokens=100,
        cost_usd=0.012,
    )

    assert roundtrip(event) == {
        "type": "token_usage",
        "input_tokens": 12,
        "output_tokens": 3,
        "cache_read_tokens": 900,
        "cache_creation_tokens": 100,
        "cost_usd": 0.012,
    }


def test_token_usage_defaults_report_no_cache_and_null_cost():
    event = roundtrip(log_events.token_usage(input_tokens=1, output_tokens=2))

    assert event["cache_read_tokens"] == 0
    assert event["cache_creation_tokens"] == 0
    assert event["cost_usd"] is None
