"""Shared pytest fixtures and collection rules."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TONY_EVALS") == "1":
        return
    skip_evals = pytest.mark.skip(reason="evals desactivadas: define TONY_EVALS=1 para ejecutarlas")
    for item in items:
        if "evals" in item.keywords:
            item.add_marker(skip_evals)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    for sub in ("config", "agents", "logs"):
        (tmp_path / sub).mkdir()
    return tmp_path
