"""`tony` command line interface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from tony import __version__
from tony.apps.cli import chat as chat_app
from tony.apps.cli import run_task as orchestration
from tony.apps.cli.chat import ChatError, ChatOptions
from tony.apps.cli.render import exit_code_for, render_json, render_text
from tony.apps.cli.run_task import RunTaskError
from tony.apps.cli.stdin_reader import StdinReader
from tony.core.orchestrator.worker import default_manager_factory, default_worker_runner_factory

app = typer.Typer(
    help="Tony: asistente personal local. Conversa con Jarvis o ejecuta tareas con un worker.",
    add_completion=False,
    no_args_is_help=True,
)

# Factories are module attributes so tests can inject doubles.
runner_factory = orchestration.default_runner_factory
manager_factory = default_manager_factory
worker_runner_factory = default_worker_runner_factory
conversation_factory = chat_app.default_conversation_factory
lines_factory = StdinReader


DEFAULT_AGENTS_DIR = Path("agents")
DEFAULT_CONFIG = Path("config/tony.yaml")


@app.command(help="Ejecuta una tarea con un agente worker y muestra el resultado.")
def run(
    agent: Annotated[
        str, typer.Argument(help="Nombre del agente worker (carpeta dentro de agents/).")
    ],
    task: Annotated[str, typer.Argument(help="Tarea a resolver, entre comillas.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Imprime el TaskResult completo como JSON y nada más.")
    ] = False,
    agents_dir: Annotated[
        Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
    ] = DEFAULT_AGENTS_DIR,
    config: Annotated[
        Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
    ] = DEFAULT_CONFIG,
) -> None:
    try:
        outcome = asyncio.run(
            orchestration.run_task(agent, task, agents_dir, config, runner_factory, manager_factory)
        )
    except RunTaskError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    for warning in outcome.warnings:
        typer.echo(warning, err=True)
    if json_output:
        typer.echo(render_json(outcome.result))
    else:
        typer.echo(render_text(outcome.result, outcome.usage, outcome.log_path))
    raise typer.Exit(exit_code_for(outcome.result.status))


@app.command(help="Conversa con el agente front (Jarvis) en la terminal.")
def chat(
    config: Annotated[
        Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
    ] = DEFAULT_CONFIG,
    agents_dir: Annotated[
        Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
    ] = DEFAULT_AGENTS_DIR,
    new: Annotated[
        bool,
        typer.Option("--new", help="Empieza una conversación nueva en vez de continuar la última."),
    ] = False,
) -> None:
    options = ChatOptions(config_path=config, agents_dir=agents_dir, new_conversation=new)
    try:
        code = asyncio.run(
            chat_app.run_chat(
                options,
                conversation_factory,
                manager_factory,
                worker_runner_factory,
                lines_factory(),
            )
        )
    except ChatError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    raise typer.Exit(code)


@app.command(help="Muestra la versión de Tony.")
def version() -> None:
    typer.echo(f"tony {__version__}")
