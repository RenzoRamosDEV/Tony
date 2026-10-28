"""Pure ${VAR} substitution over strings and nested JSON-like values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from tony.core.loader.errors import MissingEnvVar

PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def substitute_env(text: str, env: Mapping[str, str]) -> str:
    """Replace every ${VAR} in text with env[VAR]; raise MissingEnvVar if undefined."""

    def replace(match: re.Match[str]) -> str:
        var = match.group(1)
        if var not in env:
            raise MissingEnvVar(var)
        return env[var]

    return PLACEHOLDER.sub(replace, text)


def substitute_deep(value: Any, env: Mapping[str, str]) -> Any:
    """Apply substitute_env to every string inside nested lists and dicts."""
    if isinstance(value, str):
        return substitute_env(value, env)
    if isinstance(value, list):
        return [substitute_deep(item, env) for item in value]
    if isinstance(value, dict):
        return {key: substitute_deep(item, env) for key, item in value.items()}
    return value
