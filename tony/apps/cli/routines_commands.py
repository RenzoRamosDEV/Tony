from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated

import typer

from tony.apps.cli.shared import table, usage_error
from tony.core.automation.routine import Routine, RoutineError, format_weekdays
from tony.core.automation.store import InboxRow, RoutineStore, local_zone_name
from tony.core.config.secrets import resolve_home

ROUTINE_COLUMNS = ("id", "name", "time", "weekdays", "timezone", "enabled")
INBOX_COLUMNS = ("occurrence", "routine", "status", "result")
NO_ROUTINES = "no routines"
NO_RUNS = "no routine runs"


def add_routines_app(app: typer.Typer, *, now: Callable[[], datetime]) -> None:
    routines_app = typer.Typer(no_args_is_help=True, help="Manage scheduled routines.")
    app.add_typer(routines_app, name="routines")

    @contextmanager
    def store() -> Iterator[RoutineStore]:
        opened = RoutineStore(resolve_home(), clock=now)
        try:
            yield opened
        finally:
            opened.close()

    @routines_app.command("add")
    def routines_add(
        name: Annotated[str, typer.Argument(help="Routine name.")],
        time: Annotated[str, typer.Option("--time", help="Local time, HH:MM.")],
        prompt: Annotated[str, typer.Option("--prompt", help="What Tony should do.")],
        weekdays: Annotated[
            str | None,
            typer.Option("--weekdays", help="Comma list of mon,tue,wed,thu,fri,sat,sun."),
        ] = None,
        tz: Annotated[
            str | None, typer.Option("--tz", help="IANA timezone; defaults to the system zone.")
        ] = None,
    ) -> None:
        """Add a daily routine. It runs only while `tony chat` or the desktop app is running."""
        try:
            with store() as routines:
                routine_id = routines.add(
                    name=name,
                    prompt=prompt,
                    time=time,
                    weekdays=weekdays,
                    timezone=tz or local_zone_name(),
                )
        except RoutineError as error:
            usage_error(str(error))
        typer.echo(f"routine {routine_id} added")

    @routines_app.command("list")
    def routines_list() -> None:
        """List the routines."""
        with store() as routines:
            found = routines.routines()
        typer.echo(_routines_table(found) if found else NO_ROUTINES)

    @routines_app.command("remove")
    def routines_remove(routine_id: Annotated[int, typer.Argument(metavar="ID")]) -> None:
        """Delete a routine; its past runs stay in the inbox."""
        with store() as routines:
            if not routines.remove(routine_id):
                usage_error(f"unknown routine {routine_id}")

    @routines_app.command("enable")
    def routines_enable(routine_id: Annotated[int, typer.Argument(metavar="ID")]) -> None:
        """Enable a routine from now on; earlier occurrences are not run."""
        with store() as routines:
            if not routines.set_enabled(routine_id, True):
                usage_error(f"unknown routine {routine_id}")

    @routines_app.command("disable")
    def routines_disable(routine_id: Annotated[int, typer.Argument(metavar="ID")]) -> None:
        """Stop scheduling a routine."""
        with store() as routines:
            if not routines.set_enabled(routine_id, False):
                usage_error(f"unknown routine {routine_id}")

    @routines_app.command("inbox")
    def routines_inbox(
        limit: Annotated[int, typer.Option("--limit", help="Runs to print, newest first.")] = 20,
    ) -> None:
        """Show the latest routine runs."""
        if limit < 1:
            usage_error("--limit must be at least 1")
        with store() as routines:
            rows = routines.inbox(limit)
        typer.echo(_inbox_table(rows) if rows else NO_RUNS)


def _routines_table(routines: list[Routine]) -> str:
    return table(
        ROUTINE_COLUMNS,
        [
            (
                str(r.id),
                r.name,
                r.time,
                format_weekdays(r.weekdays),
                r.timezone,
                "yes" if r.enabled else "no",
            )
            for r in routines
        ],
    )


def _inbox_table(rows: list[InboxRow]) -> str:
    return table(
        INBOX_COLUMNS,
        [
            (row.occurrence_id, row.routine_name or "-", row.status, _first_line(row.result))
            for row in rows
        ],
    )


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""
