"""Secret redaction applied to every payload before it is written."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MASK = "***"
SENSITIVE_KEYS = frozenset({"authorization", "api_key", "token"})
MIN_SECRET_LENGTH = 8


def redact(payload: Any, secrets: Iterable[str]) -> Any:
    """Mask sensitive keys at any depth and every occurrence of a known secret in strings.

    Secrets shorter than MIN_SECRET_LENGTH are ignored so short .env values such as
    ports do not blank out legitimate text.
    """
    effective = [s for s in secrets if len(s) >= MIN_SECRET_LENGTH]
    return _walk(payload, effective)


def _walk(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: MASK if str(key).lower() in SENSITIVE_KEYS else _walk(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_walk(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, MASK)
        return value
    return value
