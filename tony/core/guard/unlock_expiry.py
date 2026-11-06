import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

SESSION_FILE = "config/edith.session"


class UnlockExpiry:
    """Persisted "unlocked until" timestamp; no secret is stored, just a point in time."""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = root / SESSION_FILE
        self._clock = clock

    def is_valid(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            expiry = float(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        return self._clock() < expiry

    def refresh(self, lock_after_min: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".edith.session.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(str(self._clock() + lock_after_min * 60))
            os.replace(temp, self.path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
