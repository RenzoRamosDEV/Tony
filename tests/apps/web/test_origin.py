"""Origin policy (specs/web-server): mutating HTTP and WS upgrades need an allowed Origin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.apps.web.helpers import build_test_app
from tony.apps.web.server import OriginPolicy

EVIL = {"Origin": "http://evil.local"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/settings", {"reply_mode": "voice"}),
        ("POST", "/api/tasks/t1/cancel", None),
        ("POST", "/api/tasks/t1/confirm", {"confirmation_id": "x", "approved": True}),
    ],
)
def test_mutations_with_a_foreign_or_missing_origin_are_forbidden(
    tmp_path: Path, method: str, path: str, body
) -> None:
    with build_test_app(tmp_path) as client:
        foreign = client.request(method, path, json=body, headers=EVIL)
        missing = client.request(method, path, json=body, headers={"Origin": ""})
        client.headers.pop("Origin")
        absent = client.request(method, path, json=body)

    for response in (foreign, missing, absent):
        assert response.status_code == 403
        assert response.json()["error"] == "forbidden_origin"
        assert response.json()["detail"]
    assert not (tmp_path / "memory" / "settings.json").exists()


def test_get_without_origin_is_accepted(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        client.headers.pop("Origin")
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/settings").status_code == 200


def test_localhost_origin_is_equivalent_to_loopback_host(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.patch(
            "/api/settings",
            json={"reply_mode": "voice"},
            headers={"Origin": "http://localhost:8787"},
        )

    assert response.status_code == 200
    settings_path = tmp_path / "memory" / "settings.json"
    assert json.loads(settings_path.read_text()) == {"reply_mode": "voice"}


def test_websocket_with_a_foreign_origin_is_rejected_before_any_message(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with pytest.raises(WebSocketDisconnect) as info:
            with client.websocket_connect("/ws/chat", headers=EVIL) as ws:
                ws.send_text('{"v": 1, "type": "hello", "payload": {"conversation_id": null}}')
                ws.receive_text()
        assert info.value.code in (1008, 403)
        assert client.app.state.hub.socket is None


@pytest.mark.parametrize(
    ("host", "port", "origin", "allowed"),
    [
        ("127.0.0.1", 8787, "http://127.0.0.1:8787", True),
        ("127.0.0.1", 8787, "http://localhost:8787", True),
        ("localhost", 9000, "http://127.0.0.1:9000", True),
        ("localhost", 9000, "http://localhost:9000", True),
        ("::1", 8787, "http://[::1]:8787", True),
        ("0.0.0.0", 8787, "http://0.0.0.0:8787", True),
        ("127.0.0.1", 8787, "http://127.0.0.1:8788", False),
        ("127.0.0.1", 8787, "https://127.0.0.1:8787", False),
        ("127.0.0.1", 8787, "http://evil.local", False),
        ("127.0.0.1", 8787, "", False),
        ("127.0.0.1", 8787, None, False),
        ("0.0.0.0", 8787, "http://127.0.0.1:8787", False),
    ],
)
def test_origin_policy_table(host: str, port: int, origin: str | None, allowed: bool) -> None:
    assert OriginPolicy(host, port).allows(origin) is allowed


@pytest.mark.parametrize(
    ("method", "mutating"),
    [
        ("GET", False),
        ("HEAD", False),
        ("OPTIONS", False),
        ("POST", True),
        ("PATCH", True),
        ("PUT", True),
        ("DELETE", True),
    ],
)
def test_origin_policy_guards_only_mutating_methods(method: str, mutating: bool) -> None:
    assert OriginPolicy("127.0.0.1", 8787).guards(method) is mutating
