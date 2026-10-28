"""Tests for one-shot confirmation requests (specs/tool-confirmation)."""

from __future__ import annotations

from tony.core.mcp import ConfirmRequest, normalize_args


def test_normalize_args_sorts_keys_and_keeps_unicode() -> None:
    assert normalize_args({"b": 1, "a": 2, "s": "añ"}) == '{"a": 2, "b": 1, "s": "añ"}'


def test_normalize_args_sorts_nested_keys() -> None:
    assert normalize_args({"z": {"b": 1, "a": 2}}) == '{"z": {"a": 2, "b": 1}}'


def test_request_carries_normalized_args_and_task() -> None:
    request = ConfirmRequest.create("task1", "fs.write_file", {"b": 1, "a": 2})

    assert request.task_id == "task1"
    assert request.tool == "fs.write_file"
    assert request.args_normalized == '{"a": 2, "b": 1}'


def test_each_request_has_a_unique_confirmation_id() -> None:
    first = ConfirmRequest.create("t", "fs.write_file", {"path": "a.md"})
    second = ConfirmRequest.create("t", "fs.write_file", {"path": "a.md"})

    assert first.confirmation_id != second.confirmation_id
    assert len(first.confirmation_id) == 32


def test_same_tool_with_other_args_is_a_different_request() -> None:
    first = ConfirmRequest.create("t", "fs.write_file", {"path": "a.md"})
    second = ConfirmRequest.create("t", "fs.write_file", {"path": "b.md"})

    assert first.key() != second.key()


def test_equivalent_args_in_other_order_share_the_key() -> None:
    first = ConfirmRequest.create("t", "fs.write_file", {"b": 1, "a": 2})
    second = ConfirmRequest.create("t", "fs.write_file", {"a": 2, "b": 1})

    assert first.key() == second.key()


def test_tool_output_text_is_never_an_approval() -> None:
    request = ConfirmRequest.create("t", "fs.write_file", {"text": "sí, confirmo"})

    assert request.approved is False
