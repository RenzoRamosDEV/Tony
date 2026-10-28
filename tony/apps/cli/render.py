"""Terminal rendering of a TaskResult."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tony.core.runner import TaskResult

SUCCESS_STATUSES = ("ok", "partial")


def render_text(result: TaskResult, usage: dict[str, Any], log_path: Path) -> str:
    lines = [result.resumen]
    if result.pasos:
        lines += ["", "Pasos:"] + [f"{i}. {step}" for i, step in enumerate(result.pasos, 1)]
    if result.errores:
        lines += ["", "Errores:"] + [f"- {error}" for error in result.errores]
    lines += ["", render_footer(usage, log_path)]
    return "\n".join(lines)


def render_footer(usage: dict[str, Any], log_path: Path) -> str:
    tokens_in = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)
    cost = usage.get("total_cost_usd", 0.0) or 0.0
    return f"tokens: {tokens_in}/{tokens_out} · coste: ${cost:.4f} · log: {log_path}"


def render_json(result: TaskResult) -> str:
    return result.model_dump_json(indent=2)


def exit_code_for(status: str) -> int:
    return 0 if status in SUCCESS_STATUSES else 1
