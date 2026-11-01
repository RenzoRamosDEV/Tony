import json

import pytest

from tony.apps.desktop.page_protocol import Accepted, EventReplay, PageCommandGate, Rejected
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling, TaskResult

VALID = [
    {"type": "send_message", "text": "Hola"},
    {"type": "send_message", "text": "Hola", "origin": "voice"},
    {"type": "confirm", "task_id": "t1", "decision": "allow"},
    {"type": "cancel"},
    {"type": "set_mode", "mode": "both"},
    {"type": "unlock", "pin": "1234"},
    {"type": "unlock", "pin": None},
    {"type": "listen"},
    {"type": "stop_listening"},
]


@pytest.mark.parametrize("command", VALID, ids=[f"{c['type']}-{i}" for i, c in enumerate(VALID)])
def test_valid_commands_are_forwarded_unchanged(command):
    assert PageCommandGate().accept(json.dumps(command)) == Accepted(command)


def rejected(text):
    outcome = PageCommandGate().accept(text)
    assert isinstance(outcome, Rejected)
    event = outcome.event
    assert event["type"] == "error"
    return event


def test_stop_is_refused():
    event = rejected('{"type": "stop"}')
    assert event["source"] == "stop"
    assert "stop" in event["message"]


@pytest.mark.parametrize("text", ['{"type":', "", "nope"])
def test_malformed_json_is_a_page_error(text):
    assert rejected(text)["source"] == "page"


@pytest.mark.parametrize("text", ["[]", '["listen"]', '"listen"', "1", "null"])
def test_json_that_is_not_an_object_is_a_page_error(text):
    assert rejected(text)["source"] == "page"


def test_unknown_command_names_its_type():
    event = rejected('{"type": "fly"}')
    assert event["source"] == "fly"
    assert "fly" in event["message"]


def test_invalid_unlock_never_echoes_the_pin():
    event = rejected('{"type": "unlock", "pin": "1234", "extra": true}')
    assert event["source"] == "unlock"
    assert "unlock" in event["message"]
    assert "1234" not in json.dumps(event)


def test_invalid_field_value_is_not_echoed():
    event = rejected('{"type": "set_mode", "mode": "s3cr3t"}')
    assert event["source"] == "set_mode"
    assert "s3cr3t" not in json.dumps(event)


def tool_call(task_id):
    return ev.tool_call(
        task_id, "viernes", "filesystem.read_file", "{}", Ruling(verdict="allow", rule="r")
    )


def task_result(task_id):
    return ev.task_result(
        task_id,
        "viernes",
        "ok",
        TaskResult(resumen="x"),
        input_tokens=0,
        output_tokens=0,
        elapsed_ms=0,
    )


def confirmation(task_id="t1"):
    return ev.needs_confirmation(task_id, "filesystem.delete_file", "{}", "¿Borrar?", True)


def replay(*events):
    memory = EventReplay()
    for event in events:
        memory.observe(event)
    return memory.snapshot()


def test_empty_replay_has_no_events():
    assert replay() == []


def test_snapshot_order_is_voice_mode_auth_servers_then_confirmation():
    events = [
        confirmation(),
        ev.mcp_status("viernes", "filesystem", up=True, reason=None),
        ev.auth("locked", "start", 0),
        ev.reply_mode("both"),
        ev.voice_state("loading"),
    ]
    assert replay(*events) == list(reversed(events))


def test_latest_event_of_each_kind_wins():
    latest = [ev.voice_state("ready"), ev.reply_mode("text"), ev.auth("unlocked", "unlocked", 0)]
    old = [ev.voice_state("loading"), ev.reply_mode("auto"), ev.auth("locked", "start", 0)]
    assert replay(*old, *latest) == latest


def test_latest_mcp_status_is_kept_per_agent_and_server():
    a_down = ev.mcp_status("viernes", "filesystem", up=False, reason="x")
    b = ev.mcp_status("viernes", "shell", up=True, reason=None)
    c = ev.mcp_status("jarvis", "filesystem", up=True, reason=None)
    a_up = ev.mcp_status("viernes", "filesystem", up=True, reason=None)
    assert replay(a_down, b, c, a_up) == [a_up, b, c]


def test_latest_confirmation_is_the_pending_one():
    assert replay(confirmation("t1"), confirmation("t2"))[0]["task_id"] == "t2"


@pytest.mark.parametrize("answer", [tool_call, task_result], ids=["tool_call", "task_result"])
def test_answer_for_the_same_task_clears_the_confirmation(answer):
    assert replay(confirmation("t1"), answer("t1")) == []


@pytest.mark.parametrize("answer", [tool_call, task_result], ids=["tool_call", "task_result"])
def test_answer_for_another_task_keeps_the_confirmation(answer):
    pending = confirmation("t1")
    assert replay(pending, answer("t2")) == [pending]


def test_turn_result_does_not_clear_the_confirmation():
    pending = confirmation("t1")
    assert replay(pending, ev.turn_result("jarvis", "x", "auto")) == [pending]


@pytest.mark.parametrize(
    "event",
    [
        ev.voice_level("input", 0.5),
        ev.token("jarvis", "Hola"),
        ev.error("x", "y"),
        ev.transcript("x"),
    ],
    ids=["voice_level", "token", "error", "transcript"],
)
def test_streamed_events_are_never_stored(event):
    assert replay(event) == []
