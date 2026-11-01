import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PACKAGES = [
    *(
        f"tony.core.{name}"
        for name in (
            "config",
            "loader",
            "mcp",
            "orchestrator",
            "guard",
            "voice",
            "events",
            "memory",
            "logging",
        )
    ),
    "tony.apps.cli",
    "tony.apps.desktop",
]

FOLDERS = ["agents", "config", "memory", "logs", "evals", "packaging"]


@pytest.mark.parametrize("package", PACKAGES)
def test_package_imports(package):
    assert importlib.import_module(package).__name__ == package


@pytest.mark.parametrize("folder", FOLDERS)
def test_root_folder_exists(folder):
    assert (ROOT / folder).is_dir()


@pytest.mark.parametrize("path", ["README.md", "config/.env.example"])
def test_root_file_exists(path):
    assert (ROOT / path).is_file()
