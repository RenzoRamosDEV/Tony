import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from tony.core.events.messages import TaskRequest
from tony.core.memory.actions import ActionRecord

STALE_AFTER_S = 900
MAX_NOTE_ACTIONS = 20
RECOVERABLE_OUTCOMES = frozenset({"cancelled", "timeout"})
INTERRUPTED = "interrupted"
NOTE_HEADER = "Acciones ya completadas en un intento anterior (no las repitas):"
NOTE_FOOTER = "(Los argumentos de esas llamadas no se conservan.)"


@dataclass(frozen=True)
class LoggedTask:
    task_id: str
    agent: str
    request: TaskRequest
    started_at: str
    outcome: str
    """`ok`, `error`, `cancelled`, `timeout`, or `interrupted` when no end event was logged."""
    resumed_from: str | None
    recoverable: bool


def scan_tasks(
    root: Path, clock: Callable[[], datetime], *, limit_files: int = 200
) -> list[LoggedTask]:
    """Recoverable worker tasks among the newest task logs, newest first, resumed ones hidden."""
    tasks = [
        task
        for path in _newest_logs(root, limit_files)
        if (task := _read_task(path, clock)) is not None
    ]
    resumed = {task.resumed_from for task in tasks if task.resumed_from}
    return [task for task in tasks if task.recoverable and task.task_id not in resumed]


def find_task(root: Path, task_id: str, clock: Callable[[], datetime]) -> LoggedTask | None:
    path = root / "logs" / "tasks" / f"{task_id}.jsonl"
    return _read_task(path, clock) if path.is_file() else None


def resume_request(task: LoggedTask, succeeded: list[ActionRecord]) -> TaskRequest:
    if not succeeded:
        return task.request
    lines = [
        f"- {action.tool} ({action.updated_at}, llamada {action.call_id})"
        for action in succeeded[:MAX_NOTE_ACTIONS]
    ]
    note = "\n".join([NOTE_HEADER, *lines, NOTE_FOOTER, "", task.request.contexto])
    return task.request.model_copy(update={"contexto": note})


def _newest_logs(root: Path, limit: int) -> list[Path]:
    directory = root / "logs" / "tasks"
    if not directory.is_dir():
        return []
    logs = sorted(directory.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return logs[:limit]


def _read_task(path: Path, clock: Callable[[], datetime]) -> LoggedTask | None:
    start: dict | None = None
    outcome: str | None = None
    for event in _events(path):
        if event.get("type") == "task_started" and start is None:
            start = event
        elif event.get("type") == "task_finished":
            outcome = event.get("outcome")
    if start is None:
        return None
    try:
        request = TaskRequest.model_validate(start.get("task"))
    except ValidationError:
        return None
    age_s = (clock() - datetime.fromtimestamp(path.stat().st_mtime, UTC)).total_seconds()
    final = outcome or INTERRUPTED
    stale = outcome is None and age_s > STALE_AFTER_S
    return LoggedTask(
        task_id=path.stem,
        agent=str(start.get("agent", "")),
        request=request,
        started_at=str(start.get("ts", "")),
        outcome=final,
        resumed_from=start.get("resumed_from"),
        recoverable=final in RECOVERABLE_OUTCOMES or stale,
    )


def _events(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event
