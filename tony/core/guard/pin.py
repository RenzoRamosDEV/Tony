import os
import tempfile
from pathlib import Path

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError

LOCK_FILE = "config/edith.lock"
MIN_PIN_LENGTH = 4


class PinStore:
    """Edith's PIN as an argon2 hash in config/edith.lock; the PIN itself is never stored."""

    def __init__(self, root: Path) -> None:
        self.path = root / LOCK_FILE
        self._hasher = PasswordHasher()

    def set(self, pin: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".edith.lock.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(self._hasher.hash(pin))
            os.replace(temp, self.path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    def has_valid_lock(self) -> bool:
        return self._hash() is not None

    def verify(self, pin: str) -> bool:
        stored = self._hash()
        if stored is None:
            return False
        try:
            return self._hasher.verify(stored, pin)
        except (VerificationError, InvalidHashError):
            return False

    def _hash(self) -> str | None:
        if not self.path.is_file():
            return None
        stored = self.path.read_text(encoding="utf-8").strip()
        try:
            extract_parameters(stored)
        except InvalidHashError:
            return None
        return stored
