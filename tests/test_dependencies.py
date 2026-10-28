"""Declared dependency ranges must match the APIs the code relies on."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_mcp_requirement_pins_the_2x_api() -> None:
    dependencies = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert "mcp>=2.3,<3" in dependencies
