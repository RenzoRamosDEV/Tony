"""`tony replay <ruta.jsonl> [--to-eval ID]`: inspect a task log or turn it into an eval."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tony.core.logging.replay import ReplayError, read_events, render_events, to_eval

DEFAULT_FIXTURES_DIR = Path("evals/fixtures")


def replay(
    path: Annotated[
        Path, typer.Argument(help="Registro JSONL de una tarea (logs/<fecha>/<id>.jsonl).")
    ],
    to_eval: Annotated[
        str | None,
        typer.Option("--to-eval", help="Escribe el fixture <id>.jsonl e imprime la entrada YAML."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Sobrescribe un fixture existente.")
    ] = False,
    fixtures_dir: Annotated[
        Path, typer.Option("--fixtures-dir", help="Directorio de fixtures de evals.")
    ] = DEFAULT_FIXTURES_DIR,
) -> None:
    """Imprime la secuencia de eventos de forma legible sin ejecutar ninguna tool."""
    try:
        events = read_events(path)
        if to_eval is None:
            typer.echo(render_events(events))
            return
        entry, lines, warnings = to_eval_files(events, to_eval, fixtures_dir, force)
    except ReplayError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(entry, nl=False)
    for warning in warnings:
        typer.echo(f"Aviso: {warning}", err=True)
    typer.echo(f"# fixture: {fixtures_dir / f'{to_eval}.jsonl'} ({len(lines)} eventos)", err=True)


def to_eval_files(
    events, eval_id: str, fixtures_dir: Path, force: bool
) -> tuple[str, list[str], list[str]]:
    target = fixtures_dir / f"{eval_id}.jsonl"
    if target.exists() and not force:
        raise ReplayError(f"ya existe {target}; usa --force para sobrescribirlo")
    entry, lines, warnings = to_eval(events, eval_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entry, lines, warnings
