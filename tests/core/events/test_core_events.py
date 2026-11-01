import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling, TaskResult

MADRID = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 1, 10, 0, 5, tzinfo=MADRID)
TS = "2026-11-01T09:00:05+00:00"


def clock():
    return NOW


RESULT = TaskResult(resumen="hecho", datos=["a.md"], pasos=["listar"])

CASES = [
    (
        ev.token("jarvis", "Hola", clock=clock),
        {"type": "token", "agent": "jarvis", "text": "Hola"},
    ),
    (
        ev.progress("jarvis", "Un momento"),
        {"type": "progress", "agent": "jarvis", "text": "Un momento"},
    ),
    (
        ev.task_started("t1", "viernes", "Lista notas"),
        {"type": "task_started", "task_id": "t1", "agent": "viernes", "objetivo": "Lista notas"},
    ),
    (
        ev.tool_call(
            "t1",
            "viernes",
            "shell.run",
            '{"command": "sudo"}',
            Ruling(verdict="deny", rule="shell.run/deny"),
        ),
        {
            "type": "tool_call",
            "task_id": "t1",
            "agent": "viernes",
            "tool": "shell.run",
            "args_preview": '{"command": "sudo"}',
            "verdict": "deny",
            "rule": "shell.run/deny",
            "user_decision": None,
        },
    ),
    (
        ev.needs_confirmation("t1", "filesystem.delete_file", "{}", "¿Autoriza?", True),
        {
            "type": "needs_confirmation",
            "task_id": "t1",
            "tool": "filesystem.delete_file",
            "args_preview": "{}",
            "question": "¿Autoriza?",
            "allow_always": True,
        },
    ),
    (
        ev.task_result(
            "t1", "viernes", "ok", RESULT, input_tokens=10, output_tokens=5, elapsed_ms=1200
        ),
        {
            "type": "result",
            "scope": "task",
            "task_id": "t1",
            "agent": "viernes",
            "outcome": "ok",
            "result": {"resumen": "hecho", "datos": ["a.md"], "pasos": ["listar"], "errores": []},
            "input_tokens": 10,
            "output_tokens": 5,
            "elapsed_ms": 1200,
        },
    ),
    (
        ev.turn_result("jarvis", "Hecho, señor.", "text"),
        {
            "type": "result",
            "scope": "turn",
            "agent": "jarvis",
            "text": "Hecho, señor.",
            "reply_mode": "text",
        },
    ),
    (
        ev.token_alert("t1", total_tokens=50001, limit=50000),
        {"type": "token_alert", "task_id": "t1", "total_tokens": 50001, "limit": 50000},
    ),
    (
        ev.mcp_status("viernes", "filesystem", up=False, reason="boom"),
        {
            "type": "mcp_status",
            "agent": "viernes",
            "server": "filesystem",
            "up": False,
            "reason": "boom",
        },
    ),
    (
        ev.error("front", "fallo"),
        {"type": "error", "source": "front", "message": "fallo"},
    ),
    (
        ev.auth("locked", "wrong_pin", 10),
        {"type": "auth", "state": "locked", "reason": "wrong_pin", "retry_in_s": 10},
    ),
    (
        ev.reply_mode("voice"),
        {"type": "reply_mode", "mode": "voice"},
    ),
]


@pytest.mark.parametrize(("event", "fields"), CASES, ids=[c[1]["type"] for c in CASES])
def test_builders_have_exact_fields_and_a_ts(event, fields):
    assert {key: value for key, value in event.items() if key != "ts"} == fields
    datetime.fromisoformat(event["ts"])


@pytest.mark.parametrize(("event", "fields"), CASES, ids=[c[1]["type"] for c in CASES])
def test_events_round_trip_through_json(event, fields):
    assert json.loads(json.dumps(event)) == event


def test_ts_comes_from_the_injected_clock_in_utc():
    assert ev.token("jarvis", "x", clock=clock)["ts"] == TS
    assert ev.error("s", "m", clock=clock)["ts"] == TS


def test_default_clock_is_utc_now():
    before = datetime.now(UTC)
    ts = datetime.fromisoformat(ev.reply_mode("auto")["ts"])
    assert ts.utcoffset() == timedelta(0)
    assert before <= ts <= datetime.now(UTC)


def test_audio_chunk_is_reserved_and_has_no_builder():
    assert not hasattr(ev, "audio_chunk")


def test_masking_publisher_masks_env_values_at_any_depth_and_keeps_home():
    published = []
    publish = ev.MaskingPublisher(SecretMasker({"s3cr3t"}), published.append)
    result = TaskResult(resumen="token s3cr3t", datos={"deep": ["/home/renzo/s3cr3t.md"]})

    publish(
        ev.task_result(
            "t1",
            "viernes",
            "ok",
            result,
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=0,
            clock=clock,
        )
    )

    [event] = published
    assert event["result"]["resumen"] == "token ***"
    assert event["result"]["datos"] == {"deep": ["/home/renzo/***.md"]}
    assert event["ts"] == TS


def test_no_op_publisher_accepts_events():
    assert ev.no_op(ev.reply_mode("auto")) is None
