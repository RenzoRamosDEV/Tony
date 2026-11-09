import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from tony.core.automation.occurrences import Occurrence
from tony.core.automation.routine import (
    ALL_WEEKDAYS,
    Routine,
    RoutineError,
    parse_time,
    parse_weekdays,
    validate_timezone,
)
from tony.core.config.placeholders import SecretMasker
from tony.core.logging.task_log import Clock, utc_now

ROUTINES_FILE = "memory/routines.sqlite"
BUSY_TIMEOUT_S = 2.0
RESULT_MAX_CHARS = 2000
INTERRUPTED = "interrupted"
RunStatus = Literal["queued", "ok", "error", "skipped"]
_ZONEINFO_MARKER = "zoneinfo/"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    time TEXT NOT NULL,
    weekdays INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    last_occurrence TEXT,
    active_since TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routine_runs (
    occurrence_id TEXT NOT NULL UNIQUE,
    routine_id INTEGER NOT NULL,
    scheduled_for TEXT NOT NULL,
    started_at TEXT,
    status TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT ''
);
"""
_ROUTINE_COLUMNS = "id, name, prompt, time, weekdays, timezone, enabled, active_since"
_RUN_COLUMNS = "occurrence_id, routine_id, scheduled_for, started_at, status, result"


@dataclass(frozen=True)
class RunRecord:
    occurrence_id: str
    routine_id: int
    scheduled_for: datetime
    started_at: datetime | None
    status: str
    result: str


@dataclass(frozen=True)
class InboxRow:
    occurrence_id: str
    routine_name: str | None
    status: str
    result: str


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _parse(stamp: str | None) -> datetime | None:
    return datetime.fromisoformat(stamp) if stamp else None


def local_zone_name(
    environ: Mapping[str, str] | None = None,
    *,
    read_link: Callable[[], str | None] | None = None,
) -> str:
    """The system IANA zone: a valid `TZ`, else the `/etc/localtime` link target, else UTC."""
    environ = os.environ if environ is None else environ
    candidate = environ.get("TZ", "")
    if candidate and _is_zone(candidate):
        return candidate
    target = (read_link or _localtime_target)()
    if target and _ZONEINFO_MARKER in target:
        name = target.split(_ZONEINFO_MARKER, 1)[1]
        if _is_zone(name):
            return name
    return "UTC"


def _is_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return False
    return True


def _localtime_target() -> str | None:
    try:
        return os.readlink("/etc/localtime")
    except OSError:
        return None


class RoutineStore:
    """Routine definitions and their run records in memory/routines.sqlite."""

    def __init__(
        self, root: Path, *, clock: Clock = utc_now, masker: SecretMasker | None = None
    ) -> None:
        self.path = root / ROUTINES_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S)
        self._connection.executescript(_SCHEMA)
        self._clock = clock
        self._masker = masker or SecretMasker()

    def add(self, *, name: str, prompt: str, time: str, weekdays: str | None, timezone: str) -> int:
        if not name.strip():
            raise RoutineError("the routine name must not be empty")
        if not prompt.strip():
            raise RoutineError("the routine prompt must not be empty")
        mask = ALL_WEEKDAYS if weekdays is None else parse_weekdays(weekdays)
        with self._connection:
            created = self._connection.execute(
                "INSERT INTO routines (name, prompt, time, weekdays, timezone, enabled, "
                "active_since) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (
                    name,
                    prompt,
                    parse_time(time),
                    mask,
                    validate_timezone(timezone),
                    _stamp(self._clock()),
                ),
            )
        return int(created.lastrowid)

    def routines(self) -> list[Routine]:
        found = self._connection.execute(f"SELECT {_ROUTINE_COLUMNS} FROM routines ORDER BY id")
        return [_routine(row) for row in found.fetchall()]

    def get(self, routine_id: int) -> Routine | None:
        row = self._connection.execute(
            f"SELECT {_ROUTINE_COLUMNS} FROM routines WHERE id = ?", (routine_id,)
        ).fetchone()
        return _routine(row) if row else None

    def remove(self, routine_id: int) -> bool:
        with self._connection:
            removed = self._connection.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        return removed.rowcount == 1

    def set_enabled(self, routine_id: int, enabled: bool) -> bool:
        """Enabling restarts the routine from now, so earlier occurrences are not backfilled."""
        with self._connection:
            changed = self._connection.execute(
                "UPDATE routines SET enabled = ?, active_since = CASE WHEN ? THEN ? "
                "ELSE active_since END WHERE id = ?",
                (int(enabled), int(enabled), _stamp(self._clock()), routine_id),
            )
        return changed.rowcount == 1

    def record(self, routine_id: int, occurrence: Occurrence, status: RunStatus) -> bool:
        """Store the occurrence once; False when it was already recorded."""
        with self._connection:
            inserted = self._connection.execute(
                f"INSERT OR IGNORE INTO routine_runs ({_RUN_COLUMNS}) "
                "VALUES (?, ?, ?, NULL, ?, '')",
                (occurrence.id, routine_id, _stamp(occurrence.scheduled_for), status),
            )
            self._connection.execute(
                "UPDATE routines SET last_occurrence = ? WHERE id = ?", (occurrence.id, routine_id)
            )
        return inserted.rowcount == 1

    def queued(self) -> list[RunRecord]:
        """Runs waiting to start, oldest first (claimed ones are not waiting)."""
        return self._runs("WHERE status = 'queued' AND started_at IS NULL ORDER BY scheduled_for")

    def runs(self) -> list[RunRecord]:
        return self._runs("ORDER BY scheduled_for, rowid")

    def claim(self, occurrence_id: str) -> bool:
        """Take a queued run; exactly one caller across processes gets True."""
        with self._connection:
            taken = self._connection.execute(
                "UPDATE routine_runs SET started_at = ? "
                "WHERE occurrence_id = ? AND status = 'queued' AND started_at IS NULL",
                (_stamp(self._clock()), occurrence_id),
            )
        return taken.rowcount == 1

    def finish(self, occurrence_id: str, status: RunStatus, result: str) -> None:
        text = self._masker.mask(result)[:RESULT_MAX_CHARS]
        with self._connection:
            self._connection.execute(
                "UPDATE routine_runs SET status = ?, result = ? WHERE occurrence_id = ?",
                (status, text, occurrence_id),
            )

    def skip(self, occurrence_id: str) -> None:
        self.finish(occurrence_id, "skipped", "")

    def interrupt_stale(self, older_than: timedelta) -> int:
        """Claimed runs that never finished become `error: interrupted`."""
        with self._connection:
            moved = self._connection.execute(
                "UPDATE routine_runs SET status = 'error', result = ? "
                "WHERE status = 'queued' AND started_at IS NOT NULL AND started_at < ?",
                (INTERRUPTED, _stamp(self._clock() - older_than)),
            )
        return moved.rowcount

    def inbox(self, limit: int) -> list[InboxRow]:
        found = self._connection.execute(
            "SELECT runs.occurrence_id, routines.name, runs.status, runs.result "
            "FROM routine_runs AS runs LEFT JOIN routines ON routines.id = runs.routine_id "
            "ORDER BY runs.scheduled_for DESC, runs.rowid DESC LIMIT ?",
            (limit,),
        )
        return [InboxRow(*row) for row in found.fetchall()]

    def close(self) -> None:
        self._connection.close()

    def _runs(self, tail: str) -> list[RunRecord]:
        found = self._connection.execute(f"SELECT {_RUN_COLUMNS} FROM routine_runs {tail}")
        return [
            RunRecord(row[0], row[1], _parse(row[2]), _parse(row[3]), row[4], row[5])
            for row in found.fetchall()
        ]


def _routine(row: tuple) -> Routine:
    return Routine(
        id=row[0],
        name=row[1],
        prompt=row[2],
        time=row[3],
        weekdays=row[4],
        timezone=row[5],
        enabled=bool(row[6]),
        active_since=_parse(row[7]),
    )
