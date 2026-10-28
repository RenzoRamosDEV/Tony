"""Declared dependency ranges must match the APIs the code relies on."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_mcp_requirement_pins_the_2x_api() -> None:
    dependencies = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert "mcp>=2.3,<3" in dependencies


def test_web_extra_declares_fastapi_uvicorn_and_websockets() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    web = project["project"]["optional-dependencies"]["web"]
    dev = project["dependency-groups"]["dev"]

    names = {requirement.split(">=")[0].split("[")[0] for requirement in web}
    assert names == {"fastapi", "uvicorn", "websockets"}
    assert any(requirement.startswith("httpx>=") for requirement in dev)
