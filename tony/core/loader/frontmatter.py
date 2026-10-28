"""Split a markdown document into YAML frontmatter and body."""

from __future__ import annotations

from typing import Any

import yaml

DELIMITER = "---"


class FrontmatterError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body) for text delimited by `---` lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        raise FrontmatterError("falta el frontmatter YAML delimitado por '---'")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == DELIMITER)
    except StopIteration:
        raise FrontmatterError("el frontmatter no tiene delimitador '---' de cierre") from None
    try:
        header = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter YAML inválido: {exc}") from None
    if not isinstance(header, dict):
        raise FrontmatterError("el frontmatter debe ser un mapa YAML")
    body = "\n".join(lines[end + 1 :]).strip()
    return header, body
