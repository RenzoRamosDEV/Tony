import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tony.core.memory.actions import ActionJournal
from tony.core.memory.undo import WRITE_TOOL, UndoStore, UndoUnavailableError

DIGEST_PREFIX = "sha256="


class UndoRefusedError(Exception):
    pass


@dataclass(frozen=True)
class UndoPlan:
    agent: str
    args: dict[str, Any]
    """Arguments of the guarded `filesystem.write_file` call that restores the file."""


def plan_undo(journal: ActionJournal, store: UndoStore, call_id: str) -> UndoPlan:
    """The restoring write for a journaled file write, or why it must not happen."""
    action = journal.get(call_id)
    if action is None:
        raise UndoRefusedError(f"unknown action {call_id}")
    if action.state != "succeeded":
        raise UndoRefusedError(f"action {call_id} is not succeeded")
    if action.tool != WRITE_TOOL:
        raise UndoRefusedError("not undoable")
    try:
        pre_image = store.load(call_id)
    except UndoUnavailableError as error:
        raise UndoRefusedError(str(error)) from error
    if _current_digest(pre_image.path) != action.detail:
        raise UndoRefusedError("file changed since the action")
    return UndoPlan(agent=action.agent, args={"path": pre_image.path, "content": pre_image.content})


def _current_digest(path: str) -> str | None:
    try:
        data = Path(path).expanduser().read_bytes()
    except OSError:
        return None
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()
