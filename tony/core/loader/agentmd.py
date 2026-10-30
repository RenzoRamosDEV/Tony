"""Atomic frontmatter edits that preserve the markdown body verbatim."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from tony.core.config.atomic import write_atomic
from tony.core.loader.frontmatter import DELIMITER, FrontmatterError, split_frontmatter


def edit_agent_frontmatter(
    path: Path, edit: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any]:
    """Validate, edit and atomically replace agent.md without normalizing its body."""
    with path.open(encoding="utf-8", newline="") as source:
        text = source.read()
    split_frontmatter(text)
    lines = text.splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == DELIMITER)
    header = yaml.safe_load("".join(lines[1:end]))
    if header is not None and not isinstance(header, dict):
        raise FrontmatterError("el frontmatter debe ser un mapa YAML")
    updated = edit(header or {})
    if not isinstance(updated, dict):
        raise FrontmatterError("el frontmatter editado debe ser un mapa YAML")
    serialized = yaml.safe_dump(updated, allow_unicode=True, sort_keys=False)
    write_atomic(path, f"---\n{serialized}---\n" + "".join(lines[end + 1 :]))
    return updated
