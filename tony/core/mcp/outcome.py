"""Value objects returned by the MCP manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolCallOutcome:
    ok: bool
    content: str = ""
    error: str | None = None
    duration_ms: int = 0
    outcome_unknown: bool = False

    @classmethod
    def failure(cls, error: str, duration_ms: int = 0, unknown: bool = False) -> ToolCallOutcome:
        return cls(ok=False, error=error, duration_ms=duration_ms, outcome_unknown=unknown)


@dataclass(frozen=True)
class McpServerStatus:
    name: str
    state: Literal["ready", "error"]
    error: str | None
    tool_count: int
    allow: list[str] | None
