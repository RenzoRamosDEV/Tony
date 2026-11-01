from typing import Any

import yaml

from tony.core.config.errors import DefinitionError

DELIMITER = "---"


def split_frontmatter(text: str, file: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0] != DELIMITER or DELIMITER not in lines[1:]:
        raise DefinitionError(file, None, "missing '---' delimited YAML frontmatter")
    closing = lines.index(DELIMITER, 1)
    frontmatter = _parse_yaml("\n".join(lines[1:closing]), file)
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise DefinitionError(file, None, "system prompt body must not be empty")
    return frontmatter, body


def _parse_yaml(text: str, file: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise DefinitionError(file, None, f"invalid YAML frontmatter: {error}") from error
    if not isinstance(data, dict):
        raise DefinitionError(file, None, "frontmatter must be a YAML mapping")
    return data
