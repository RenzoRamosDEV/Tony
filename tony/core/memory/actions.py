import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from tony.core.config.placeholders import SecretMasker
from tony.core.logging.task_log import Clock, utc_now

ACTIONS_FILE = "memory/actions.sqlite"
DETAIL_MAX_CHARS = 200
BUSY_TIMEOUT_S = 2.0
ActionState = Literal["prepared", "dispatched", "succeeded", "failed", "outcome_unknown"]
ACTION_STATES: tuple[str, ...] = get_args(ActionState)
INTERRUPTED_DETAIL = "interrupted: the process ended while the call was running"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    call_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_digest TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""
_COLUMNS = "call_id, task_id, agent, tool, args_digest, state, created_at, updated_at, detail"


@dataclass(frozen=True)
class ActionRecord:
    call_id: str
    task_id: str
    agent: str
    tool: str
    args_digest: str
    state: str
    created_at: str
    updated_at: str
    detail: str


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


class ActionJournal:
    """Per-call state of guarded tool executions in memory/actions.sqlite; only digests, no args."""

    def __init__(self, root: Path, masker: SecretMasker, *, clock: Clock = utc_now) -> None:
        path = root / ACTIONS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S)
        self._connection.executescript(_SCHEMA)
        self._masker = masker
        self._clock = clock

    def prepared(self, task_id: str, agent: str, tool: str, args_digest: str) -> str:
        call_id = str(uuid.uuid4())
        now = _stamp(self._clock())
        with self._connection:
            self._connection.execute(
                f"INSERT INTO actions ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (call_id, task_id, agent, tool, args_digest, "prepared", now, now, ""),
            )
        return call_id

    def transition(self, call_id: str, state: ActionState, detail: str = "") -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE actions SET state = ?, detail = ?, updated_at = ? WHERE call_id = ?",
                (state, self._safe_detail(detail), _stamp(self._clock()), call_id),
            )

    def recover_interrupted(self, before: datetime) -> int:
        """Mark `dispatched` rows last touched before `before` as `outcome_unknown`."""
        with self._connection:
            moved = self._connection.execute(
                "UPDATE actions SET state = 'outcome_unknown', detail = ?, updated_at = ? "
                "WHERE state = 'dispatched' AND updated_at < ?",
                (INTERRUPTED_DETAIL, _stamp(self._clock()), _stamp(before)),
            )
        return moved.rowcount

    def for_task(self, task_id: str, state: str | None = None) -> list[ActionRecord]:
        """The actions of one task, oldest first."""
        where, parameters = ("AND state = ?", (state,)) if state else ("", ())
        found = self._connection.execute(
            f"SELECT {_COLUMNS} FROM actions WHERE task_id = ? {where} ORDER BY created_at, rowid",
            (task_id, *parameters),
        )
        return [ActionRecord(*row) for row in found.fetchall()]

    def list(self, state: str | None = None, limit: int = 20) -> list[ActionRecord]:
        where, parameters = ("WHERE state = ?", (state,)) if state else ("", ())
        found = self._connection.execute(
            f"SELECT {_COLUMNS} FROM actions {where} ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (*parameters, limit),
        )
        return [ActionRecord(*row) for row in found.fetchall()]

    def get(self, call_id: str) -> ActionRecord | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM actions WHERE call_id = ?", (call_id,)
        ).fetchone()
        return ActionRecord(*row) if row else None

    def close(self) -> None:
        self._connection.close()

    def _safe_detail(self, detail: str) -> str:
        return self._masker.mask(detail)[:DETAIL_MAX_CHARS]


def open_journal(root: Path, masker: SecretMasker) -> ActionJournal | None:
    """The existing journal, or None when none was ever written (nothing is created)."""
    if not (root / ACTIONS_FILE).is_file():
        return None
    return ActionJournal(root, masker)


def open_for_host(root: Path, masker: SecretMasker, *, clock: Clock = utc_now) -> ActionJournal:
    """The journal of a process that runs tools; calls a previous process left `dispatched` have
    an unknown outcome and are marked so. Nothing is ever re-executed."""
    started = clock()
    journal = ActionJournal(root, masker, clock=clock)
    journal.recover_interrupted(started)
    return journal
