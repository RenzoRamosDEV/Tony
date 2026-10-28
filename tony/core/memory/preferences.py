"""User preferences: hand-editable markdown list, appended atomically, never summarised."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tony.core.memory.atomic import write_atomic

OMITTED_HEADER = "(…{count} líneas anteriores omitidas; ejecuta /memoria para verlas)"
DEFAULT_MAX_LINES = 200


class PreferencesStore:
    def __init__(self, path: Path, max_lines: int = DEFAULT_MAX_LINES) -> None:
        self.path = path
        self._max_lines = max_lines

    def read(self) -> list[str]:
        return [line for line in self._raw().splitlines() if line.strip()]

    def append(self, text: str, today: date | None = None) -> str:
        line = f"- [{(today or date.today()).isoformat()}] {text}"
        current = self._raw()
        if current and not current.endswith("\n"):
            current += "\n"
        write_atomic(self.path, current + line + "\n")
        return line

    def injection_block(self) -> str:
        lines = self.read()
        omitted = len(lines) - self._max_lines
        if omitted > 0:
            lines = [OMITTED_HEADER.format(count=omitted), *lines[omitted:]]
        return "\n".join(lines)

    def _raw(self) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")
