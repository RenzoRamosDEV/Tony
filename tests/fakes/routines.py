import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tony.core.automation.store import ROUTINES_FILE, RoutineStore


def seed_due_routine(home: Path, *, prompt: str = "resume mis notas") -> int:
    """A daily UTC routine whose time passed five minutes ago and that was added hours before."""
    now = datetime.now(UTC)
    store = RoutineStore(home, clock=lambda: now - timedelta(hours=2))
    routine_id = store.add(
        name="mañana",
        prompt=prompt,
        time=(now - timedelta(minutes=5)).strftime("%H:%M"),
        weekdays=None,
        timezone="UTC",
    )
    store.close()
    return routine_id


def run_statuses(home: Path) -> list[str]:
    path = home / ROUTINES_FILE
    if not path.exists():
        return []
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT status FROM routine_runs")]
    finally:
        connection.close()
