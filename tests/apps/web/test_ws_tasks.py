"""Delegated tasks over WS (specs/ws-chat-protocol): events, confirmations, cancel, usage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.apps.web.helpers import (
    advance,
    build_test_app,
    delegating,
    drain_until,
    open_chat,
    send,
)

MOVE_ARGS = {
    "source": "/home/renzo/notas/tmp.md",
    "destination": "/home/renzo/notas/.trash/tmp.md",
}
CONFIRM = [
    ("tool", "filesystem.read_file", {"path": "/n/a.md"}),
    ("confirm", "filesystem.move_file", MOVE_ARGS),
]
MOVE = {"mueve": CONFIRM}
BIG = {"input_tokens": 41200, "output_tokens": 9900, "total_cost_usd": 0.31}
SMALL = {"input_tokens": 20000, "output_tokens": 5000}


def types(seen: list[dict]) -> list[str]:
    return [m["type"] for m in seen]


def payload_of(seen: list[dict[str, Any]], type_: str) -> dict[str, Any]:
    return next(m for m in seen if m["type"] == type_)["payload"]


def result_status(seen: list[dict[str, Any]]) -> str:
    return payload_of(seen, "task.result")["result"]["status"]


def test_task_events_tool_calls_confirmation_by_ws_and_result(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[delegating("mueve")], scripts=MOVE) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "mueve"})
            seen = drain_until(ws, "task.needs_confirmation")
            asked = seen[-1]
            confirmation_id = asked["payload"]["confirmation_id"]
            send(ws, "confirm", {"confirmation_id": confirmation_id, "approved": True})
            rest = drain_until(ws, "assistant.final")

    assert types(seen) == [
        "user.accepted",
        "task.queued",
        "task.running",
        "mcp.status",
        "task.started",
        "tool.call",
        "task.progress",
        "tool.result",
        "tool.call",
        "task.progress",
        "task.needs_confirmation",
    ]
    task_id = seen[1]["task_id"]
    log_path = Path(seen[1]["payload"]["log_path"])
    assert log_path.exists() and log_path.name == f"{task_id}.jsonl"
    assert log_path.parent.parent == tmp_path / "logs"
    assert all(m["task_id"] == task_id for m in seen[1:])
    assert seen[5]["payload"] == {"tool": "filesystem.read_file", "args": {"path": "/n/a.md"}}
    assert set(seen[7]["payload"]) == {"tool", "ok", "duration_ms", "error"}
    assert asked == {
        "v": 1,
        "type": "task.needs_confirmation",
        "seq": asked["seq"],
        "conversation_id": conversation,
        "task_id": task_id,
        "payload": {
            "confirmation_id": confirmation_id,
            "tool": "filesystem.move_file",
            "args": MOVE_ARGS,
            "expires_in_s": 60,
        },
    }
    assert types(rest) == [
        "task.confirmed",
        "tool.result",
        "task.finished",
        "usage",
        "task.result",
        "usage",
        "assistant.final",
    ]
    assert rest[0]["payload"] == {"confirmation_id": confirmation_id, "approved": True}
    assert result_status(rest) == "ok"
    assert rest[3]["task_id"] == task_id and rest[5]["payload"]["task_id"] is None


def test_rejection_by_http_cancels_as_not_confirmed(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[delegating("mueve")], scripts=MOVE) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "mueve"})
            asked = drain_until(ws, "task.needs_confirmation")[-1]
            response = client.post(
                f"/api/tasks/{asked['task_id']}/confirm",
                json={"confirmation_id": asked["payload"]["confirmation_id"], "approved": False},
            )
            rest = drain_until(ws, "assistant.final")

    assert response.status_code == 200
    assert payload_of(rest, "task.cancelled") == {"reason": "not_confirmed"}
    assert result_status(rest) == "cancelled"


def test_confirmation_expires_after_sixty_seconds(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[delegating("mueve")], scripts=MOVE) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "mueve"})
            asked = drain_until(ws, "task.needs_confirmation")[-1]
            advance(client, 61)
            rest = drain_until(ws, "assistant.final")
            confirmation_id = asked["payload"]["confirmation_id"]
            send(ws, "confirm", {"confirmation_id": confirmation_id, "approved": True})
            late = ws.receive_json()

    assert payload_of(rest, "task.cancelled") == {"reason": "not_confirmed"}
    assert late["type"] == "error" and late["payload"]["code"] == "invalid_confirmation"


def test_cancel_by_ws_ends_the_task_as_cancelled_by_user(tmp_path: Path) -> None:
    scripts = {"larga": [("sleep", 100)]}
    with build_test_app(tmp_path, turns=[delegating("larga")], scripts=scripts) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "tarea"})
            task_id = drain_until(ws, "task.running")[-1]["task_id"]
            send(ws, "cancel", {"task_id": task_id})
            rest = drain_until(ws, "assistant.final")

    assert payload_of(rest, "task.cancelled") == {"reason": "user"}
    assert result_status(rest) == "cancelled"
    assert client.app.state.runner.interrupts == 1


def test_wait_phrase_arrives_after_three_seconds(tmp_path: Path) -> None:
    scripts = {"lenta": [("sleep", 5)]}
    with build_test_app(tmp_path, turns=[delegating("lenta")], scripts=scripts) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "tarea"})
            drain_until(ws, "task.started")
            advance(client, 2.9)
            advance(client, 0.1)
            wait = ws.receive_json()
            advance(client, 2)
            drain_until(ws, "assistant.final")

    assert wait["type"] == "assistant.wait" and wait["payload"] == {"text": "Dame un momento."}


def test_subtask_events_carry_parent_id_and_cumulative_usage_alerts(tmp_path: Path) -> None:
    scripts = {
        "padre": [("subtask", "investigador", "hijo"), ("usage", BIG)],
        "hijo": [("tool", "fs.read", {"path": "x"}), ("usage", SMALL)],
    }
    with build_test_app(tmp_path, turns=[delegating("padre")], scripts=scripts) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "delega"})
            seen = drain_until(ws, "assistant.final")

    root = seen[1]["task_id"]
    started = next(m for m in seen if m["type"] == "subtask.started")
    child = started["payload"]["task_id"]
    assert started["task_id"] == root and started["payload"]["agent"] == "investigador"
    child_call = next(m for m in seen if m["type"] == "tool.call" and m["task_id"] == child)
    assert child_call["payload"] == {"tool": "fs.read", "args": {"path": "x"}, "parent_id": root}
    finished = next(m for m in seen if m["type"] == "subtask.finished")
    assert finished["payload"] == {"task_id": child, "status": "done"}
    usages = {m.get("task_id"): m["payload"] for m in seen if m["type"] == "usage"}
    assert usages[child] == {
        "input_tokens": 20000,
        "output_tokens": 5000,
        "cost_usd": 0.0,
        "cumulative_tokens": 25000,
        "alert": False,
    }
    assert usages[root] == {
        "input_tokens": 41200,
        "output_tokens": 9900,
        "cost_usd": 0.31,
        "cumulative_tokens": 76100,
        "alert": True,
    }


def test_secrets_are_redacted_in_forwarded_events(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text("API_TOKEN=supersecreto123\n", encoding="utf-8")
    scripts = {"lista": [("tool", "api.call", {"key": "supersecreto123"})]}
    with build_test_app(tmp_path, turns=[delegating("lista")], scripts=scripts) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "lista"})
            seen = drain_until(ws, "assistant.final")

    assert payload_of(seen, "tool.call")["args"] == {"key": "***"}
    assert "supersecreto123" not in str(seen)
