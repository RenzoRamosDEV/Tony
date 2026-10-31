"""GET/PATCH /api/settings (specs/web-api)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.apps.web.helpers import build_test_app, settle


def test_get_reports_yaml_mode_without_a_settings_file(tmp_path: Path) -> None:
    with build_test_app(tmp_path, settings_yaml="reply_mode: auto\n") as client:
        assert client.get("/api/settings").json() == {
            "reply_mode": "auto",
            "reply_mode_source": "yaml",
        }


def test_get_reports_the_persisted_mode(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "settings.json").write_text('{"reply_mode": "text"}', encoding="utf-8")
    with build_test_app(tmp_path) as client:
        assert client.get("/api/settings").json() == {
            "reply_mode": "text",
            "reply_mode_source": "settings",
        }


def test_patch_persists_a_valid_mode(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.patch("/api/settings", json={"reply_mode": "voice"})

    assert response.status_code == 200
    assert response.json() == {"reply_mode": "voice", "reply_mode_source": "settings"}
    assert json.loads((tmp_path / "memory" / "settings.json").read_text()) == {
        "reply_mode": "voice"
    }


def test_patch_rejects_an_invalid_mode_without_touching_the_file(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir()
    settings = tmp_path / "memory" / "settings.json"
    settings.write_text('{"reply_mode": "text"}', encoding="utf-8")
    with build_test_app(tmp_path) as client:
        response = client.patch("/api/settings", json={"reply_mode": "loud"})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error" and response.json()["detail"]
    assert settings.read_text() == '{"reply_mode": "text"}'


def test_patch_rejects_any_mode_other_than_voice_without_touching_the_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "memory").mkdir()
    settings = tmp_path / "memory" / "settings.json"
    settings.write_text('{"reply_mode": "voice"}', encoding="utf-8")
    with build_test_app(tmp_path) as client:
        response = client.patch("/api/settings", json={"reply_mode": "text"})

    assert response.status_code == 403
    assert response.json()["error"] == "reply_mode_locked"
    assert settings.read_text() == '{"reply_mode": "voice"}'


def test_patched_mode_applies_to_the_next_message(tmp_path: Path) -> None:
    turns = [{"display_text": "Hola", "speech_text": "Hola"}]
    with build_test_app(tmp_path, turns=turns) as client:
        assert client.patch("/api/settings", json={"reply_mode": "voice"}).status_code == 200
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"v": 1, "type": "hello", "seq": 1, "payload": {"conversation_id": None}})
            assert ws.receive_json()["payload"]["reply_mode"] == "voice"
            ws.send_json({"v": 1, "type": "user.text", "seq": 2, "payload": {"text": "hola"}})
            accepted = ws.receive_json()
            settle(client)

    assert accepted["type"] == "user.accepted" and accepted["payload"]["effective_mode"] == "voice"
