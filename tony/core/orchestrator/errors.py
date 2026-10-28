"""Errors raised by the orchestrator; `code` is the stable identifier channels rely on."""

from __future__ import annotations

QUEUE_FULL = "queue_full"
UNKNOWN_TASK = "unknown_task"
INVALID_CONFIRMATION = "invalid_confirmation"
INVALID_TRANSITION = "invalid_transition"


class OrchestratorError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
