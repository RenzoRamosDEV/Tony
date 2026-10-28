"""GET /api/health (specs/web-api)."""

from __future__ import annotations

from pathlib import Path

from tests.apps.web.helpers import build_test_app, delegating, settle
from tony import __version__
from tony.core.mcp import McpServerStatus


def test_health_before_any_task(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "front": "jarvis",
        "worker": "viernes",
        "mcp": [],
    }


def test_health_lists_the_servers_of_the_running_generation(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[delegating("lista")]) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"v": 1, "type": "hello", "payload": {"conversation_id": None}})
            ws.receive_json()
            ws.send_json({"v": 1, "type": "user.text", "payload": {"text": "lista"}})
            while ws.receive_json()["type"] != "assistant.final":
                pass
            settle(client)
            manager = client.app.state.doubles.managers[-1]
            manager.statuses = {
                "filesystem": McpServerStatus("filesystem", "ready", None, 11, None)
            }
            response = client.get("/api/health")

    assert response.json()["mcp"] == [{"name": "filesystem", "state": "ready", "tool_count": 11}]
