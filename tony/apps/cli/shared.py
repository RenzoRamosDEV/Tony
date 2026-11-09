import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

import typer

from tony.core.config.placeholders import SecretMasker
from tony.core.config.secrets import load_variables
from tony.core.events.messages import TaskResult
from tony.core.evidence.render import source_lines
from tony.core.memory.actions import ActionJournal, open_for_host, open_journal

USAGE_ERROR = 2
TASK_FAILED = 1


def usage_error(message: str) -> NoReturn:
    typer.echo(f"tony: {message}", err=True)
    raise typer.Exit(USAGE_ERROR)


def table(columns: tuple[str, ...], body: list[tuple[str, ...]]) -> str:
    rows = [columns, *body]
    widths = [max(len(row[index]) for row in rows) for index in range(len(columns))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def report_result(result: TaskResult) -> None:
    """Print a worker task result as `tony run` does and exit non-zero when it has errors."""
    typer.echo(result.model_dump_json())
    for line in source_lines(result.datos):
        typer.echo(line, err=True)
    if result.errores:
        raise typer.Exit(TASK_FAILED)


@contextmanager
def read_journal(root: Path) -> Iterator[ActionJournal | None]:
    """The existing journal for inspection; no recovery runs and no file is created."""
    variables = load_variables(root, os.environ)
    journal = open_journal(root, SecretMasker(variables.env_file_values.values()))
    try:
        yield journal
    finally:
        if journal is not None:
            journal.close()


@contextmanager
def running_journal(root: Path) -> Iterator[ActionJournal]:
    variables = load_variables(root, os.environ)
    journal = open_for_host(root, SecretMasker(variables.env_file_values.values()))
    try:
        yield journal
    finally:
        journal.close()
