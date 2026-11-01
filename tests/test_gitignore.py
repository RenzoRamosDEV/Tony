from pathlib import Path

import pytest

GITIGNORE = Path(__file__).resolve().parents[1] / ".gitignore"

REQUIRED = [
    "requirements/",
    ".claude/",
    ".serena/",
    "apm_modules/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    "mutants/",
    "config/.env",
    "config/edith.lock",
    "config/engine-auth.json",
    "logs/",
    "memory/*.sqlite*",
    "memory/preferences.md",
    "memory/settings.json",
    "evals/runs/",
    "samples/",
    "tony/apps/desktop/web/dist/",
    "node_modules/",
]


@pytest.fixture(scope="module")
def entries():
    return {line.strip() for line in GITIGNORE.read_text().splitlines()}


@pytest.mark.parametrize("entry", REQUIRED)
def test_gitignore_contains_entry(entries, entry):
    assert entry in entries
