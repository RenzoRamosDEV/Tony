"""`tony` command line interface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from tony import __version__
from tony.apps.cli import agents_cli, doctor_cli, engine_cli, mcp_cli, replay_cli, voice_cli
from tony.apps.cli import chat as chat_app
from tony.apps.cli import run_task as orchestration
from tony.apps.cli.chat import ChatError, ChatOptions
from tony.apps.cli.render import exit_code_for, render_json, render_text
from tony.apps.cli.run_task import RunTaskError
from tony.apps.cli.stdin_reader import StdinReader
from tony.apps.web.options import WebOptions, is_loopback
from tony.core.channels.bootstrap import RuntimeOptions
from tony.core.config import ConfigError, load_settings
from tony.core.orchestrator.worker import default_manager_factory

app = typer.Typer(
    help="Tony: asistente personal local. Conversa con Jarvis o ejecuta tareas con un worker.",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(engine_cli.app, name="engine")
app.add_typer(mcp_cli.app, name="mcp", help="Gestiona los servidores MCP de un agente.")
app.add_typer(agents_cli.app, name="agents", help="Lista los agentes y subagentes o muestra uno.")
app.command("doctor", help="Diagnostica la instalación (✓/✗ con sugerencias).")(doctor_cli.doctor)
app.add_typer(doctor_cli.config_app, name="config", help="Valida la configuración sin red.")
app.command("replay", help="Muestra los eventos de un registro JSONL o lo convierte en eval.")(
    replay_cli.replay
)
app.add_typer(voice_cli.app, name="voice", help="Calienta y mide los modelos de voz locales.")

# Factories are module attributes so tests can inject doubles.
# None defers to the selected agent's engine (tony.core.runner.engine_factory).
runner_factory = None
manager_factory = default_manager_factory
worker_runner_factory = None
conversation_factory = None
lines_factory = StdinReader
watch_factory = None
web_serve = None


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
                watch=watch_factory() if watch_factory is not None else None,
            )
        )
    except ChatError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    raise typer.Exit(code)


def load_web_serve():
    from tony.apps.web.server import serve

    return serve


REMOTE_REFUSED = (
    "El host {host} no es loopback; usa --allow-remote para escuchar fuera de la máquina "
    "(sin autenticación ni HTTPS)."
)
REMOTE_WARNING = (
    "Aviso: el servidor escucha en {host}:{port}, fuera de loopback, sin autenticación ni HTTPS."
)
WEB_EXTRA_MISSING = "El chat web necesita el extra tony[web]: instala con `uv sync --extra web`."


@app.command(help="Arranca el chat web local (servidor HTTP y WebSocket) con Jarvis.")
def web(
    port: Annotated[
        int | None, typer.Option("--port", help="Puerto de escucha (por defecto web.port, 8787).")
    ] = None,
    host: Annotated[
        str | None,
        typer.Option("--host", help="Dirección de escucha (por defecto web.host, 127.0.0.1)."),
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Abre el navegador en la página del chat al arrancar.")
    ] = False,
    allow_remote: Annotated[
        bool,
        typer.Option(
            "--allow-remote", help="Permite escuchar fuera de loopback (sin autenticación)."
        ),
    ] = False,
    config: Annotated[
        Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
    ] = DEFAULT_CONFIG,
    agents_dir: Annotated[
        Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
    ] = DEFAULT_AGENTS_DIR,
) -> None:
    try:
        settings = load_settings(config)
    except ConfigError as exc:
        typer.echo(f"Configuración inválida en {config}: {exc}", err=True)
        raise typer.Exit(2) from None
    host = host or settings.web.host
    port = port or settings.web.port
    if not is_loopback(host):
        if not allow_remote:
            typer.echo(REMOTE_REFUSED.format(host=host), err=True)
            raise typer.Exit(2)
        typer.echo(REMOTE_WARNING.format(host=host, port=port), err=True)
    try:
        serve = web_serve or load_web_serve()
    except ImportError:
        typer.echo(WEB_EXTRA_MISSING, err=True)
        raise typer.Exit(2) from None
    options = WebOptions(
        host, port, RuntimeOptions(config_path=config, agents_dir=agents_dir), open_browser
    )
    try:
        asyncio.run(serve(options))
    except ChatError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None


@app.command(help="Muestra la versión de Tony.")
def version() -> None:
    typer.echo(f"tony {__version__}")
