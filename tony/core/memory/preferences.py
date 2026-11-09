import re
from pathlib import Path
from typing import cast, get_args

from tony.core.config.placeholders import SecretMasker
from tony.core.events.core_events import ReplyMode

PREFERENCES_FILE = "memory/preferences.md"
REPLY_MODES: tuple[str, ...] = get_args(ReplyMode)
_MODE_LINE = re.compile(r"^\s*reply_mode:\s*(\S*)\s*$")


class PreferencesFile:
    """The user's preferences in memory/preferences.md: free `- ` lines and the reply mode."""

    def __init__(self, root: Path, masker: SecretMasker | None = None) -> None:
        self.path = root / PREFERENCES_FILE
        self._masker = masker or SecretMasker()

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8") if self.path.is_file() else ""

    def append_line(self, text: str) -> None:
        line = " ".join(text.split())
        if not line:
            raise ValueError("text must not be empty")
        entry = f"- {self._masker.mask(line)}"
        lines = self._lines()
        if entry not in lines:
            self._write([*lines, entry])

    def reply_mode(self) -> ReplyMode | None:
        modes = [mode for line in self._lines() if (mode := _mode_of(line)) in REPLY_MODES]
        return cast(ReplyMode, modes[-1]) if modes else None

    def set_reply_mode(self, mode: str) -> None:
        if mode not in REPLY_MODES:
            raise ValueError(f"invalid reply mode '{mode}': use one of {', '.join(REPLY_MODES)}")
        new_line = f"reply_mode: {mode}"
        lines: list[str] = []
        replaced = False
        for line in self._lines():
            if _mode_of(line) is None:
                lines.append(line)
            elif not replaced:
                lines.append(new_line)
                replaced = True
        self._write(lines if replaced else [*lines, new_line])

    def _lines(self) -> list[str]:
        return self.read().splitlines()

    def _write(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _mode_of(line: str) -> str | None:
    match = _MODE_LINE.match(line)
    return match.group(1) if match else None
