"""Exact rendering of TaskResult for the terminal."""

from __future__ import annotations

import json
from pathlib import Path

from tony.apps.cli.render import exit_code_for, render_footer, render_json, render_text
from tony.core.runner import TaskResult

USAGE = {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.01, "num_turns": 2}
LOG = Path("logs/20261028/abc.jsonl")


def test_full_text_layout() -> None:
    result = TaskResult(status="ok", resumen="Hecho", pasos=["a", "b"], errores=["e1"])

    assert render_text(result, USAGE, LOG) == (
        "Hecho\n\nPasos:\n1. a\n2. b\n\nErrores:\n- e1\n\n"
        "tokens: 10/5 · coste: $0.0100 · log: logs/20261028/abc.jsonl"
    )


def test_text_without_steps_or_errors_has_only_summary_and_footer() -> None:
    result = TaskResult(status="ok", resumen="Hecho")

    assert render_text(result, USAGE, LOG) == (
        "Hecho\n\ntokens: 10/5 · coste: $0.0100 · log: logs/20261028/abc.jsonl"
    )


def test_footer_defaults_to_zero_when_usage_is_missing() -> None:
    assert render_footer({}, LOG) == "tokens: 0/0 · coste: $0.0000 · log: logs/20261028/abc.jsonl"


def test_footer_treats_null_cost_as_zero() -> None:
    assert render_footer({"total_cost_usd": None}, LOG).startswith("tokens: 0/0 · coste: $0.0000")


def test_json_is_pretty_printed_with_two_spaces() -> None:
    text = render_json(TaskResult(status="ok", resumen="r"))

    assert text.splitlines()[1] == '  "status": "ok",'
    assert json.loads(text)["resumen"] == "r"


def test_exit_codes() -> None:
    assert [exit_code_for(s) for s in ("ok", "partial", "error", "cancelled", "timeout")] == [
        0,
        0,
        1,
        1,
        1,
    ]
