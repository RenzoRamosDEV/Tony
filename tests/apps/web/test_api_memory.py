"""GET /api/memory (specs/web-api)."""

from __future__ import annotations

from pathlib import Path

from tests.apps.web.helpers import build_test_app

PREFERENCES = "- [2026-10-28] Prefiere respuestas breves\n- [2026-10-28] Usa español\n"


def test_memory_with_two_preferences(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "preferences.md").write_text(PREFERENCES, encoding="utf-8")
    with build_test_app(tmp_path) as client:
        assert client.get("/api/memory").json() == {"content": PREFERENCES, "lines": 2}


def test_memory_without_a_file(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        assert client.get("/api/memory").json() == {"content": "", "lines": 0}
