import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UNDO_DIR = "memory/undo"
MAX_PREIMAGE_BYTES = 1_048_576
WRITE_TOOL = "filesystem.write_file"
_CALL_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class UndoUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class PreImage:
    path: str
    content: str


def content_digest(content: str) -> str:
    return "sha256=" + hashlib.sha256(content.encode("utf-8")).hexdigest()


class UndoStore:
    """Previous content of files overwritten by `filesystem.write_file`, one entry per call id."""

    def __init__(self, root: Path) -> None:
        self._directory = root / UNDO_DIR

    def keep(self, call_id: str, tool_id: str, args: dict[str, Any]) -> None:
        if tool_id != WRITE_TOOL or not _CALL_ID.match(call_id):
            return
        given = str(args["path"])
        previous = _readable_previous(Path(given).expanduser())
        if previous is None:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        self._directory.chmod(0o700)
        _write_private(self._directory / call_id, previous)
        _write_private(self._directory / f"{call_id}.json", json.dumps({"path": given}).encode())

    def written_digest(self, tool_id: str, args: dict[str, Any]) -> str:
        return content_digest(args["content"]) if tool_id == WRITE_TOOL else ""

    def is_undoable(self, call_id: str) -> bool:
        return bool(_CALL_ID.match(call_id)) and self._sidecar(call_id).is_file()

    def load(self, call_id: str) -> PreImage:
        if not self.is_undoable(call_id):
            raise UndoUnavailableError(f"no stored content for {call_id}")
        path = json.loads(self._sidecar(call_id).read_text(encoding="utf-8"))["path"]
        content = (self._directory / call_id).read_bytes().decode("utf-8")
        return PreImage(path=path, content=content)

    def _sidecar(self, call_id: str) -> Path:
        return self._directory / f"{call_id}.json"


def _readable_previous(path: Path) -> bytes | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_PREIMAGE_BYTES:
            return None
        data = path.read_bytes()
        data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return data


def _write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
