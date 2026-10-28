"""POST /api/tasks/{id}/confirm and /cancel (specs/web-api) against a scripted worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.apps.web.helpers import build_test_app, delegating, drain_until, open_chat, send, settle

CONFIRM = [("confirm", "filesystem.move_file", {"source": "a", "destination": "b"})]


def start_task(ws: Any, text: str = "mueve") -> dict[str, Any]:
    send(ws, "user.text", {"text": text})
    return drain_until(ws, "task.needs_confirmation")[-1]


def test_confirm_approves_by_http_and_the_tool_runs(tmp_path: Path) -> None:
    with build_test_app(
        tmp_path, turns=[delegating("mueve")], scripts={"mueve": CONFIRM}
    ) as client:
        with open_chat(client) as (ws, _):
            asked = start_task(ws)
            task_id, confirmation_id = asked["task_id"], asked["payload"]["confirmation_id"]

            response = client.post(
                f"/api/tasks/{task_id}/confirm",
                json={"confirmation_id": confirmation_id, "approved": True},
            )
            seen = drain_until(ws, "assistant.final")

    assert response.status_code == 200 and response.json() == {"ok": True}
    confirmed = next(m for m in seen if m["type"] == "task.confirmed")
    assert confirmed["payload"] == {"confirmation_id": confirmation_id, "approved": True}
    assert client.app.state.doubles.runners[0].inner.state.steps == ["filesystem.move_file(a, b)"]
    assert (
        next(m for m in seen if m["type"] == "task.result")["payload"]["result"]["status"] == "ok"
    )


def test_confirm_rejects_by_http_and_the_task_is_cancelled(tmp_path: Path) -> None:
    with build_test_app(
        tmp_path, turns=[delegating("mueve")], scripts={"mueve": CONFIRM}
    ) as client:
        with open_chat(client) as (ws, _):
            asked = start_task(ws)
            response = client.post(
                f"/api/tasks/{asked['task_id']}/confirm",
                json={"confirmation_id": asked["payload"]["confirmation_id"], "approved": False},
            )
            seen = drain_until(ws, "assistant.final")

    assert response.status_code == 200
    assert client.app.state.doubles.runners[0].inner.state.steps == []
    assert (
        next(m for m in seen if m["type"] == "task.result")["payload"]["result"]["status"]
        == "cancelled"
    )
    assert (
        next(m for m in seen if m["type"] == "task.cancelled")["payload"]["reason"]
        == "not_confirmed"
    )


def test_invalid_foreign_and_repeated_confirmations_are_409(tmp_path: Path) -> None:
    with build_test_app(
        tmp_path, turns=[delegating("mueve")], scripts={"mueve": CONFIRM}
    ) as client:
        with open_chat(client) as (ws, _):
            asked = start_task(ws)
            task_id, confirmation_id = asked["task_id"], asked["payload"]["confirmation_id"]

            unknown = client.post(
                f"/api/tasks/{task_id}/confirm", json={"confirmation_id": "nope", "approved": True}
            )
            foreign = client.post(
                "/api/tasks/t-1/confirm",
                json={"confirmation_id": confirmation_id, "approved": True},
            )
            assert client.app.state.hub.router.pending() is not None
            ws.send_json(
                {
                    "v": 1,
                    "type": "confirm",
                    "payload": {"confirmation_id": confirmation_id, "approved": True},
                }
            )
            drain_until(ws, "task.confirmed")
            repeated = client.post(
                f"/api/tasks/{task_id}/confirm",
                json={"confirmation_id": confirmation_id, "approved": False},
            )
            drain_until(ws, "assistant.final")

    for response in (unknown, foreign, repeated):
        assert response.status_code == 409
        assert response.json()["error"] == "invalid_confirmation"
    assert client.app.state.doubles.runners[0].inner.state.steps == ["filesystem.move_file(a, b)"]


def test_cancel_an_active_task_and_a_finished_one(tmp_path: Path) -> None:
    scripts = {"larga": [("sleep", 100)]}
    with build_test_app(tmp_path, turns=[delegating("larga")], scripts=scripts) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "tarea"})
            task_id = drain_until(ws, "task.running")[-1]["task_id"]

            response = client.post(f"/api/tasks/{task_id}/cancel")
            seen = drain_until(ws, "assistant.final")
            again = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 200 and response.json() == {"ok": True}
    assert next(m for m in seen if m["type"] == "task.cancelled")["payload"] == {"reason": "user"}
    assert (
        next(m for m in seen if m["type"] == "task.result")["payload"]["result"]["status"]
        == "cancelled"
    )
    assert again.status_code == 200


def test_cancel_unknown_task_is_404(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.post("/api/tasks/nope/cancel")

    assert response.status_code == 404
    assert response.json()["error"] == "unknown_task" and "nope" in response.json()["detail"]
    settle(client) if client.portal else None
