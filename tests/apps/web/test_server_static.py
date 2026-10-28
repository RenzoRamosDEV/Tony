"""Compiled frontend from `/`, fallback page without `dist`, `--open` hook (specs/web-server)."""

from __future__ import annotations

from pathlib import Path

from tests.apps.web.helpers import build_test_app


def write_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Tony</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('tony')", encoding="utf-8")
    return dist


def test_compiled_frontend_is_served_from_root_and_assets(tmp_path: Path) -> None:
    dist = write_dist(tmp_path)
    with build_test_app(tmp_path, dist=dist) as client:
        index = client.get("/")
        asset = client.get("/assets/app.js")

    assert index.status_code == 200 and index.headers["content-type"].startswith("text/html")
    assert index.text == "<!doctype html><title>Tony</title>"
    assert asset.status_code == 200 and asset.text == "console.log('tony')"


def test_without_dist_root_serves_the_fallback_page(tmp_path: Path) -> None:
    with build_test_app(tmp_path, dist=tmp_path / "missing") as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "npm run build" in response.text and "tony/apps/web/frontend" in response.text


def test_open_browser_calls_the_hook_with_the_root_url_after_startup(tmp_path: Path) -> None:
    opened: list[str] = []
    with build_test_app(tmp_path, open_browser=True, open_url=opened.append) as client:
        assert opened == ["http://127.0.0.1:8787/"]
        client.get("/api/health")
    with build_test_app(tmp_path, open_url=opened.append):
        pass
    assert opened == ["http://127.0.0.1:8787/"]
