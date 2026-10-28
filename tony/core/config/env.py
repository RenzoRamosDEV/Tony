"""Environment map used for ${VAR} substitution and secret redaction."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

EnvMap = dict[str, str]


def _file_values(path: Path) -> EnvMap:
    return {key: value for key, value in dotenv_values(path).items() if value}


def load_env(path: Path) -> EnvMap:
    """Merge config/.env pairs under the process environment (the process wins)."""
    return {**_file_values(path), **os.environ}


def dotenv_secrets(path: Path) -> list[str]:
    """Non-empty values declared in config/.env; these are redacted from logs."""
    return list(_file_values(path).values())
