"""Confirmation port: a one-shot approval bound to one tool call."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol


def normalize_args(args: dict[str, Any]) -> str:
    """Canonical JSON of the arguments (sorted keys, unicode preserved)."""
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class ConfirmRequest:
    confirmation_id: str
    task_id: str
    tool: str
    args_normalized: str
    approved: bool = False

    @classmethod
    def create(cls, task_id: str, tool: str, args: dict[str, Any]) -> ConfirmRequest:
        return cls(uuid.uuid4().hex, task_id, tool, normalize_args(args))

    def key(self) -> tuple[str, str, str]:
        return (self.task_id, self.tool, self.args_normalized)


class ConfirmGate(Protocol):
    async def confirm(self, request: ConfirmRequest) -> bool: ...
