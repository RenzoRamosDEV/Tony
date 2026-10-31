"""Reconnection (specs/ws-chat-protocol): replay after last_seq, state, resync, one socket."""

from __future__ import annotations

from pathlib import Path

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
    wait_detached,
)

MANY_TOOLS = {"muchas": [("tool", f"fs.read{i}", {"i": i}) for i in range(8)]}
CONFIRM = {"mueve": [("confirm", "filesystem.move_file", {"source": "a", "destination": "b"})]}


def test_reconnect_replays_only_after_last_seq_without_duplicating_text(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[delegating("muchas")], scripts=MANY_TOOLS) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "lee"})
            first = [ws.receive_json() for _ in range(18)]
        wait_detached(client)
        for _ in range(20):
            settle(client)

        with client.websocket_connect("/ws/chat") as ws2:
            ok = hello(ws2, conversation, last_seq=18)
            replayed = drain_until(ws2, "assistant.final")

    assert [m["seq"] for m in first] == list(range(1, 19))
    assert ok["payload"]["state"]["turn_in_progress"] is False
    assert [m["seq"] for m in replayed] == list(range(19, ok["payload"]["last_seq"] + 1))
    finals = [m for m in first + replayed if m["type"] == "assistant.final"]
    assert len(finals) == 1
    assert finals[0]["payload"]["display_text"] == "Resultado: guion completado"


def test_reconnect_with_a_pending_confirmation_reports_the_state(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[delegating("mueve")], scripts=CONFIRM) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "mueve"})
            asked = drain_until(ws, "task.needs_confirmation")[-1]
        wait_detached(client)
        advance(client, 20)

        with client.websocket_connect("/ws/chat") as ws2:
            ok = hello(ws2, conversation, last_seq=asked["seq"])
            confirmation_id = asked["payload"]["confirmation_id"]
            send(ws2, "confirm", {"confirmation_id": confirmation_id, "approved": True})
            drain_until(ws2, "assistant.final")

    state = ok["payload"]["state"]
    assert state["turn_in_progress"] is True
    assert state["active_tasks"] == [
        {"task_id": asked["task_id"], "parent_id": None, "status": "waiting_confirmation"}
    ]
    pending = state["pending_confirmation"]
    assert pending["confirmation_id"] == confirmation_id
    assert pending["task_id"] == asked["task_id"]
    assert pending["tool"] == "filesystem.move_file"
    assert pending["args"] == {"source": "a", "destination": "b"}
    assert 39 <= pending["expires_in_s"] <= 40


def test_reconnect_older_than_the_buffer_requests_a_resync(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with open_chat(client) as (_, conversation):
            pass
        wait_detached(client)
        stream = client.app.state.hub.stream

        async def publish_many() -> None:
            for i in range(700):
                await stream.publish("task.progress", {"i": i})

        client.portal.call(publish_many)
        with client.websocket_connect("/ws/chat") as ws2:
            ok = hello(ws2, conversation, last_seq=10)
            send(ws2, "set_mode", {"reply_mode": "loud"})
            after = ws2.receive_json()

    assert ok["payload"]["resync"] is True and ok["payload"]["last_seq"] == 700
    assert after["type"] == "error" and after["payload"]["code"] == "reply_mode_locked"


def test_second_socket_is_rejected_and_relayed_after_close(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=["Hola."]) as client:
        with open_chat(client) as (ws, conversation):
            with client.websocket_connect("/ws/chat") as second:
                busy = hello(second, conversation)
                try:
                    second.receive_json()
                    code = None
                except WebSocketDisconnect as exc:
                    code = exc.code
            send(ws, "user.text", {"text": "hola"})
            drain_until(ws, "assistant.final")
        wait_detached(client)

        with client.websocket_connect("/ws/chat") as third:
            relayed = hello(third, conversation)

    assert busy["type"] == "error" and busy["payload"]["code"] == "conversation_busy"
    assert code == 1008
    assert relayed["type"] == "hello.ok" and relayed["payload"]["conversation_id"] == conversation
