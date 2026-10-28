"""Load eval definitions from YAML, rejecting duplicates and malformed entries."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from tony.core.evals.models import ConversationEval, TaskEval
from tony.core.loader.errors import format_validation_error


class EvalLoadError(Exception):
    pass


def load_task_evals(path: Path) -> list[TaskEval]:
    return _load(path, TaskEval.model_validate)


def load_conversation_evals(path: Path) -> list[ConversationEval]:
    return _load(path, ConversationEval.model_validate)


def _load[E](path: Path, parse: Callable[[Any], E]) -> list[E]:
    if not path.is_file():
        raise EvalLoadError(f"no existe {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EvalLoadError(f"{path.name}: YAML inválido: {exc}") from None
    if not isinstance(raw, list):
        raise EvalLoadError(f"{path.name}: debe ser una lista de evals")
    evals: list[E] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        try:
            parsed = parse(item)
        except ValidationError as exc:
            label = item.get("id", f"#{index}") if isinstance(item, dict) else f"#{index}"
            raise EvalLoadError(f"{path.name} [{label}]: {format_validation_error(exc)}") from None
        eval_id = parsed.id
        if eval_id in seen:
            raise EvalLoadError(f"{path.name}: id duplicado '{eval_id}'")
        seen.add(eval_id)
        evals.append(parsed)
    return evals
