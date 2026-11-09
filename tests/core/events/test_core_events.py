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
        ev.needs_confirmation(
            "t1",
            "gmail.send_email",
            "{}",
            "¿Autoriza?",
            False,
            approval_id="A1",
            args_digest="d1",
            policy_version="v1",
            expires_at=datetime(2026, 11, 1, 10, 1, 5, tzinfo=MADRID),
            preview={"to": "a@x.com", "bytes": 5},
        ),
        {
            "type": "needs_confirmation",
            "task_id": "t1",
            "tool": "gmail.send_email",
            "args_preview": "{}",
            "question": "¿Autoriza?",
            "allow_always": False,
            "approval_id": "A1",
            "args_digest": "d1",
            "policy_version": "v1",
            "expires_at": "2026-11-01T09:01:05+00:00",
            "preview": {"to": "a@x.com", "bytes": 5},
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
    (
        ev.turn_started("jarvis", "voice", "auto", speaks=True, writes=False),
        {
            "type": "turn_started",
            "agent": "jarvis",
            "origin": "voice",
            "reply_mode": "auto",
            "speaks": True,
            "writes": False,
        },
    ),
    (
        ev.transcript("¿Qué hora es?"),
        {"type": "transcript", "text": "¿Qué hora es?"},
    ),
    (
        ev.voice_state("unavailable", "voice extra not installed"),
        {"type": "voice_state", "state": "unavailable", "reason": "voice extra not installed"},
    ),
    (
        ev.voice_state("ready"),
        {"type": "voice_state", "state": "ready", "reason": None},
    ),
    (
        ev.voice_level("input", 0.25),
        {"type": "voice_level", "source": "input", "level": 0.25},
    ),
    (
        ev.voice_level("output", 1.0),
        {"type": "voice_level", "source": "output", "level": 1.0},
    ),
]


@pytest.mark.parametrize(
    ("event", "fields"), CASES, ids=[f"{c[1]['type']}-{i}" for i, c in enumerate(CASES)]
)
def test_builders_have_exact_fields_and_a_ts(event, fields):
    assert {key: value for key, value in event.items() if key != "ts"} == fields
    datetime.fromisoformat(event["ts"])


@pytest.mark.parametrize(
    ("event", "fields"), CASES, ids=[f"{c[1]['type']}-{i}" for i, c in enumerate(CASES)]
)
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


def test_new_conversation_events_use_the_injected_clock():
    assert (
        ev.turn_started("jarvis", "text", "both", speaks=True, writes=True, clock=clock)["ts"] == TS
    )
    assert ev.transcript("x", clock=clock)["ts"] == TS
    assert ev.voice_state("loading", clock=clock)["ts"] == TS


def test_masking_publisher_masks_transcripts_and_voice_reasons():
    published = []
    publish = ev.MaskingPublisher(SecretMasker({"s3cr3t"}), published.append)

    publish(ev.transcript("mi clave es s3cr3t"))
    publish(ev.voice_state("unavailable", "fallo s3cr3t"))

    assert [published[0]["text"], published[1]["reason"]] == ["mi clave es ***", "fallo ***"]


def test_voice_level_uses_the_injected_clock():
    assert ev.voice_level("input", 0.0, clock=clock)["ts"] == TS


def test_audio_devices_event_shape():
    from tony.core.voice.engines.devices import DeviceInfo

    event = ev.audio_devices(
        (DeviceInfo(name="Mic A", kind="input", is_default=True),),
        (),
        selected_input="Mic A",
        selected_output=None,
    )
    assert event["type"] == "audio_devices"
    assert event["input"] == [{"name": "Mic A", "kind": "input", "is_default": True}]
    assert event["selected_input"] == "Mic A"
    assert event["input_fallback_warning"] is None


def test_conversations_event_shape():
    from tony.core.memory.history import ConversationSummary

    event = ev.conversations([ConversationSummary("c1", "Hola", 2, "2026-11-01T09:00:00+00:00")])

    assert {key: value for key, value in event.items() if key != "ts"} == {
        "type": "conversations",
        "items": [
            {
                "id": "c1",
                "title": "Hola",
                "message_count": 2,
                "last_ts": "2026-11-01T09:00:00+00:00",
            }
        ],
    }
    assert json.loads(json.dumps(event)) == event


def test_conversations_event_uses_the_injected_clock_and_may_be_empty():
    event = ev.conversations([], clock=clock)

    assert (event["ts"], event["items"]) == (TS, [])


def test_needs_confirmation_omits_unset_approval_fields():
    event = ev.needs_confirmation("t1", "x", "{}", "q", False, preview={})

    assert set(event) == {
        "type",
        "ts",
        "task_id",
        "tool",
        "args_preview",
        "question",
        "allow_always",
    }


def test_clarification_requested_shape():
    event = ev.clarification_requested(
        "r1", "t1", "viernes", "¿Qué cuenta?", ["a", "b"], clock=clock
    )

    assert event == {
        "type": "clarification_requested",
        "ts": TS,
        "request_id": "r1",
        "task_id": "t1",
        "agent": "viernes",
        "question": "¿Qué cuenta?",
        "options": ["a", "b"],
    }
    assert json.loads(json.dumps(event)) == event


def test_clarification_requested_without_options_has_an_empty_list():
    assert ev.clarification_requested("r1", "t1", "viernes", "q", [])["options"] == []


def test_clarification_requested_masks_secrets_in_question_and_options():
    published = []
    publish = ev.MaskingPublisher(SecretMasker({"s3cr3t"}), published.append)

    publish(ev.clarification_requested("r1", "t1", "viernes", "¿Es s3cr3t?", ["s3cr3t"]))

    [event] = published
    assert event["question"] == "¿Es ***?"
    assert event["options"] == ["***"]


def test_task_started_origin_only_when_given():
    assert "origin" not in ev.task_started("t1", "viernes", "o")
    assert ev.task_started("t1", "viernes", "o", origin="routine")["origin"] == "routine"
