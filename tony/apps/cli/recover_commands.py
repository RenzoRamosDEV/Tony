import asyncio
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from tony.apps.cli.shared import (
    TASK_FAILED,
    read_journal,
    report_result,
    running_journal,
    table,
    usage_error,
)
from tony.core.config.errors import DefinitionError
from tony.core.config.secrets import resolve_home
from tony.core.memory.actions import ActionJournal, ActionRecord
from tony.core.memory.undo import WRITE_TOOL, UndoStore
from tony.core.orchestrator.runner import (
    NotWorkerError,
    RunDeps,
    ToolUnavailableError,
    run_guarded_call,
    run_task,
)
from tony.core.recovery.tasks import LoggedTask, find_task, resume_request, scan_tasks
from tony.core.recovery.undo import UndoRefusedError, plan_undo

TASK_COLUMNS = ("task", "agent", "outcome", "started", "objetivo")
ACTION_COLUMNS = ("task", "call", "tool", "undo")
NOTHING_TO_RECOVER = "no tasks to recover"
TASK_ID = re.compile(r"^[0-9a-f]{32}$")

RunDepsFactory = Callable[[Path, ActionJournal], RunDeps]


def add_recover_app(
    app: typer.Typer, *, run_deps: RunDepsFactory, now: Callable[[], datetime]
) -> None:
    recover_app = typer.Typer(no_args_is_help=True, help="Recover unfinished tasks.")
    app.add_typer(recover_app, name="recover")

    @recover_app.command("list")
    def recover_list(
        limit: Annotated[int, typer.Option("--limit", help="Tasks to print, newest first.")] = 20,
    ) -> None:
        """List cancelled, timed-out and interrupted tasks with their succeeded actions."""
        if limit < 1:
            usage_error("--limit must be at least 1")
        root = resolve_home()
        tasks = scan_tasks(root, now)[:limit]
        if not tasks:
            typer.echo(NOTHING_TO_RECOVER)
            return
        store = UndoStore(root)
        with read_journal(root) as journal:
            actions = {task.task_id: _succeeded(journal, task.task_id) for task in tasks}
        typer.echo(_tasks_table(tasks))
        rows = [
            (task_id, action.call_id, action.tool, _undo_label(store, action))
            for task_id, records in actions.items()
            for action in records
        ]
        if rows:
            typer.echo("")
            typer.echo(table(ACTION_COLUMNS, rows))

    @recover_app.command("resume")
    def recover_resume(
        task_id: Annotated[str, typer.Argument(metavar="TASK_ID", help="Task id to continue.")],
    ) -> None:
        """Run the task again as a NEW task, noting the actions that already succeeded."""
        root = resolve_home()
        task = find_task(root, task_id, now) if TASK_ID.match(task_id) else None
        if task is None:
            usage_error(f"unknown task {task_id}")
        if not task.recoverable:
            usage_error(f"task {task_id} is not recoverable")
        try:
            with running_journal(root) as journal:
                request = resume_request(task, journal.for_task(task_id, "succeeded"))
                result = asyncio.run(
                    run_task(task.agent, request, run_deps(root, journal), resumed_from=task_id)
                )
        except (ValidationError, DefinitionError, NotWorkerError) as error:
            usage_error(str(error))
        report_result(result)

    @recover_app.command("undo")
    def recover_undo(
        call_id: Annotated[str, typer.Argument(metavar="CALL_ID", help="Journaled write call.")],
    ) -> None:
        """Restore a file overwritten by a journaled write, through a new guarded write."""
        root = resolve_home()
        try:
            with running_journal(root) as journal:
                plan = plan_undo(journal, UndoStore(root), call_id)
                reply = asyncio.run(
                    run_guarded_call(
                        plan.agent,
                        WRITE_TOOL,
                        plan.args,
                        run_deps(root, journal),
                        objetivo=f"undo {call_id}",
                    )
                )
        except (UndoRefusedError, DefinitionError, NotWorkerError, ToolUnavailableError) as error:
            usage_error(str(error))
        if reply.is_error:
            typer.echo(f"tony: {reply.text}", err=True)
            raise typer.Exit(TASK_FAILED)
        typer.echo(f"restored {plan.args['path']}")


def _succeeded(journal: ActionJournal | None, task_id: str) -> list[ActionRecord]:
    return journal.for_task(task_id, "succeeded") if journal else []


def _undo_label(store: UndoStore, action: ActionRecord) -> str:
    return "undoable" if store.is_undoable(action.call_id) else "not undoable"


def _tasks_table(tasks: list[LoggedTask]) -> str:
    return table(
        TASK_COLUMNS,
        [(t.task_id, t.agent, t.outcome, t.started_at, t.request.objetivo) for t in tasks],
    )
