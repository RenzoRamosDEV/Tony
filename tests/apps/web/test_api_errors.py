"""Uniform error format (specs/web-api)."""

from __future__ import annotations

from pathlib import Path

from tests.apps.web.helpers import build_test_app


def test_unknown_api_route_is_404_not_found(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.get("/api/nada")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "detail": response.json()["detail"]}
    assert response.json()["detail"]


def test_invalid_body_is_422_validation_error(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        wrong_type = client.patch("/api/settings", json={"reply_mode": 3})
        not_json = client.patch(
            "/api/settings", content=b"{no", headers={"Content-Type": "application/json"}
        )
        missing = client.post("/api/tasks/t1/confirm", json={"approved": True})

    for response in (wrong_type, not_json, missing):
        assert response.status_code == 422
        assert response.json()["error"] == "validation_error" and response.json()["detail"]


def test_wrong_method_is_405(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.delete("/api/health")

    assert response.status_code == 405
    assert response.json()["error"] == "method_not_allowed"
