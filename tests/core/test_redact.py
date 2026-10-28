"""Unit tests for secret redaction."""

from __future__ import annotations

import pytest

from tony.core.logging import redact


@pytest.mark.parametrize(
    "key", ["Authorization", "authorization", "API_KEY", "api_key", "token", "TOKEN"]
)
def test_sensitive_keys_are_masked_case_insensitively(key: str) -> None:
    assert redact({key: "value"}, secrets=[]) == {key: "***"}


def test_sensitive_key_is_masked_at_any_depth() -> None:
    payload = {"args": {"options": {"API_KEY": "xyz"}, "items": [{"token": "t"}]}}

    assert redact(payload, secrets=[]) == {
        "args": {"options": {"API_KEY": "***"}, "items": [{"token": "***"}]}
    }


def test_secret_substring_is_replaced_inside_strings() -> None:
    assert redact({"query": "token s3cr3tvalue fin"}, secrets=["s3cr3tvalue"]) == {
        "query": "token *** fin"
    }


def test_secret_inside_list_items_is_replaced() -> None:
    assert redact(["a s3cr3tvalue b", 1, None], secrets=["s3cr3tvalue"]) == ["a *** b", 1, None]


@pytest.mark.parametrize("short", ["8787", "", "1234567"])
def test_secrets_shorter_than_eight_chars_are_ignored(short: str) -> None:
    assert redact({"port": f"x{short}y"}, secrets=[short]) == {"port": f"x{short}y"}


def test_secret_of_exactly_eight_chars_is_redacted() -> None:
    assert redact({"v": "pre12345678post"}, secrets=["12345678"]) == {"v": "pre***post"}


def test_non_string_scalars_are_untouched() -> None:
    assert redact({"n": 42, "b": True, "x": None}, secrets=["12345678"]) == {
        "n": 42,
        "b": True,
        "x": None,
    }


def test_unrelated_keys_keep_their_values() -> None:
    assert redact({"path": "a.md", "tokens": "plural is fine"}, secrets=[]) == {
        "path": "a.md",
        "tokens": "plural is fine",
    }
