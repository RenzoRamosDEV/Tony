"""End-to-end WS flow over the FastAPI app (specs/ws-chat-protocol): hello, turns, errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.apps.web.helpers import (
    advance,
    build_test_app,
    delegating,
    drain_until,
    hello,
    open_chat,
    send,
    settle,
)
from tony.core.runner.conversation import FrontTurn

STREAMED = {"display_text": "Hola, Renzo", "speech_text": None, "chunks": ["Hola", ", Renzo"]}
USAGE = {"input_tokens": 1200, "output_tokens": 80, "total_cost_usd": 0.01, "num_turns": 1}


def types(seen: list[dict]) -> list[str]:
    return [m["type"] for m in seen]


def test_message_before_hello_is_rejected_without_creating_anything(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with client.websocket_connect("/ws/chat") as ws:
            send(ws, "user.text", {"text": "hola"})
            error = ws.receive_json()
        assert error["type"] == "error" and error["payload"]["code"] == "hello_required"
        assert client.app.state.runner.prompts == []
        assert client.get("/api/conversations").json() == []


def test_hello_null_opens_a_new_conversation(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ok = hello(ws)
    assert ok["type"] == "hello.ok" and ok["payload"]["last_seq"] == 0
    assert ok["payload"]["state"] == {
        "turn_in_progress": False,
        "active_tasks": [],
        "pending_confirmation": None,
    }
    assert ok["conversation_id"] == ok["payload"]["conversation_id"]


def test_streamed_turn_sends_accepted_deltas_usage_and_final(tmp_path: Path) -> None:
    turn = FrontTurn(text="", structured=STREAMED, usage=USAGE)
    with build_test_app(tmp_path, turns=[turn]) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "hola"})
            seen = drain_until(ws, "assistant.final")

    assert types(seen) == [
        "user.accepted",
        "assistant.delta",
        "assistant.delta",
        "usage",
        "assistant.final",
    ]
    assert [m["seq"] for m in seen] == [1, 2, 3, 4, 5]
    assert all(m["conversation_id"] == conversation for m in seen)
    assert seen[0]["payload"]["effective_mode"] == "text"
    assert [m["payload"]["text"] for m in seen[1:3]] == ["Hola", ", Renzo"]
    assert len({m["message_id"] for m in seen[1:3]} | {seen[4]["message_id"]}) == 1
    assert seen[3]["payload"] == {
        "task_id": None,
        "input_tokens": 1200,
        "output_tokens": 80,
        "cost_usd": 0.01,
        "cumulative_tokens": 1280,
        "alert": False,
    }
    assert "task_id" not in seen[3]
    assert seen[4]["payload"] == {
        "display_text": "Hola, Renzo",
        "speech_text": None,
        "message_id": seen[4]["message_id"],
    }


def test_turn_without_chunks_sends_no_deltas(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=["Hola."]) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "hola"})
            seen = drain_until(ws, "assistant.final")

    assert types(seen) == ["user.accepted", "usage", "assistant.final"]


def test_voice_prefix_sets_the_effective_mode_and_speech_text(tmp_path: Path) -> None:
    turns = [{"display_text": "Son las nueve.", "speech_text": "Son las nueve"}]
    with build_test_app(tmp_path, turns=turns, settings_yaml="reply_mode: text\n") as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v qué hora es"})
            seen = drain_until(ws, "assistant.final")

    assert seen[0]["payload"]["effective_mode"] == "voice"
    assert seen[-1]["payload"]["speech_text"] == "Son las nueve"
    assert client.app.state.runner.prompts[0].endswith("qué hora es")


def test_turn_in_progress_and_empty_text_are_errors(tmp_path: Path) -> None:
    scripts = {"lenta": [("sleep", 10)]}
    turns = [delegating("lenta"), "Otra."]
    with build_test_app(tmp_path, turns=turns, scripts=scripts) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "   "})
            assert ws.receive_json()["payload"]["code"] == "empty_text"
            send(ws, "user.text", {"text": "tarea"})
            drain_until(ws, "task.running")
            send(ws, "user.text", {"text": "otra"})
            rejected = drain_until(ws, "error")[-1]
            settle(client)
            assert len(client.app.state.runner.prompts) == 1
            advance(client, 10)
            drain_until(ws, "assistant.final")

    assert rejected["payload"]["code"] == "turn_in_progress"


def test_set_mode_persists_or_fails(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=["Hola."]) as client:
        with open_chat(client) as (ws, _):
            send(ws, "set_mode", {"reply_mode": "text"})
            assert ws.receive_json()["payload"]["code"] == "reply_mode_locked"
            send(ws, "set_mode", {"reply_mode": "loud"})
            assert ws.receive_json()["payload"]["code"] == "reply_mode_locked"
            send(ws, "set_mode", {"reply_mode": "voice"})
            send(ws, "user.text", {"text": "hola"})
            accepted = ws.receive_json()
            drain_until(ws, "assistant.final")

    assert accepted["payload"]["effective_mode"] == "voice"
    persisted = json.loads((tmp_path / "memory" / "settings.json").read_text())
    assert persisted == {"reply_mode": "voice"}


@pytest.mark.parametrize(
    ("type_", "code"), [("audio.start", "voice_unavailable"), ("ping", "unknown_type")]
)
def test_audio_start_is_a_known_type_and_ping_is_not(tmp_path: Path, type_: str, code: str) -> None:
    with build_test_app(tmp_path) as client:
        with open_chat(client) as (ws, _):
            send(ws, type_, {})
            error = ws.receive_json()
            send(ws, "set_mode", {"reply_mode": "text"})
            settle(client)

    assert error["type"] == "error" and error["payload"]["code"] == code
    assert error["payload"]["code"] != "not_implemented"


def test_oversized_envelope_closes_with_1009(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with client.websocket_connect("/ws/chat") as ws:
            hello(ws)
            text = "a" * 39_900
            ws.send_text(json.dumps({"v": 1, "type": "user.text", "payload": {"text": text}}))
            error = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as info:
                ws.receive_json()
        assert error["payload"]["code"] == "message_too_large"
        assert info.value.code == 1009
        assert client.app.state.runner.prompts == []


def test_wrong_version_closes_with_1002_and_invalid_json_does_not(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_text("{not json")
            bad = ws.receive_json()
            ws.send_text('{"v": 2, "type": "hello", "seq": 1, "payload": {}}')
            versioned = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as info:
                ws.receive_json()
    assert bad["payload"]["code"] == "bad_envelope" and bad["seq"] == 0
    assert versioned["payload"]["code"] == "bad_envelope"
    assert info.value.code == 1002


def test_failed_turn_reports_turn_failed_and_keeps_the_socket(tmp_path: Path) -> None:
    turns = [FrontTurn(text="No pude completar el turno.", error="boom"), "Sigo."]
    with build_test_app(tmp_path, turns=turns) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "hola"})
            seen = drain_until(ws, "assistant.final")
            send(ws, "user.text", {"text": "otra"})
            again = drain_until(ws, "assistant.final")

    assert types(seen) == ["user.accepted", "error", "usage", "assistant.final"]
    assert seen[1]["payload"] == {"code": "turn_failed", "detail": "boom"}
    assert seen[3]["payload"]["display_text"] == "No pude completar el turno."
    assert again[-1]["payload"]["display_text"] == "Sigo."


def test_finding_7_bad_payload_is_reported_over_the_wire_without_closing(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with open_chat(client) as (ws, _):
            send(ws, "confirm", {"confirmation_id": "a3f", "approved": "false"})
            rejected = ws.receive_json()
            send(ws, "hello", {"conversation_id": None, "last_seq": "abc"})
            second = ws.receive_json()
            send(ws, "user.text", {"text": "sigo aquí"})
            accepted = drain_until(ws, "user.accepted")[-1]

    assert rejected["payload"]["code"] == "bad_payload" and rejected["seq"] == 0
    assert second["payload"]["code"] == "bad_payload"
    assert accepted["payload"]["client_id"] is None
