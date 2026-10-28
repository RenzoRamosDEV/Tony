"""`tony mcp add|remove|list`: manage the MCP servers declared in tool/tool.json."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer

from tony.apps.cli.render import render_table
from tony.core.config import ConfigError, TonySettings, load_env, load_settings
from tony.core.loader import AgentLoadError, AgentSpec, HttpServer, load_agent, load_all
from tony.core.loader.tooljson import (
    ToolJsonError,
    read_tool_json,
    remove_server,
    upsert_server,
    write_tool_json,
)
from tony.core.mcp.ports import ManagerFactory

app = typer.Typer(
    help="Gestiona los servidores MCP de un agente (agents/<agente>/tool/tool.json).",
    no_args_is_help=True,
)

DEFAULT_AGENTS_DIR = Path("agents")
DEFAULT_CONFIG = Path("config/tony.yaml")
LIST_OPTIONS = {"--allow": "allow", "--confirm": "confirm"}
MAP_OPTIONS = {"--header": "headers", "--env": "env"}
COLUMNS = ("agente", "servidor", "transporte", "estado", "tools", "allow", "confirm")
ALL = "todas"
NONE = "-"


@dataclass
class AddRequest:
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    agent: str | None = None
    allow: list[str] = field(default_factory=list)
    confirm: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    force: bool = False

    def server(self) -> dict[str, Any]:
        if self.url is not None:
            return {"url": self.url, **({"headers": self.headers} if self.headers else {})}
        server: dict[str, Any] = {"command": self.command}
        if self.args:
            server["args"] = self.args
        if self.env:
            server["env"] = self.env
        return server


def parse_add_tokens(tokens: list[str]) -> AddRequest:
    """Extract Tony's options from any position; the rest is the URL or command + args."""
    request = AddRequest()
    positional: list[str] = []
    pending = list(tokens)
    while pending:
        token = pending.pop(0)
        if token == "--force":
            request.force = True
        elif token == "--agent":
            request.agent = _value(token, pending)
        elif token in LIST_OPTIONS:
            getattr(request, LIST_OPTIONS[token]).append(_value(token, pending))
        elif token in MAP_OPTIONS:
            key, value = _key_value(token, _value(token, pending))
            getattr(request, MAP_OPTIONS[token])[key] = value
        else:
            positional.append(token)
    if positional:
        first, *rest = positional
        if first.startswith(("http://", "https://")):
            request.url, request.args = first, rest
        else:
            request.command, request.args = first, rest
    return request


def _value(option: str, pending: list[str]) -> str:
    if not pending:
        raise ValueError(f"la opción {option} necesita un valor")
    return pending.pop(0)


def _key_value(option: str, text: str) -> tuple[str, str]:
    key, separator, value = text.partition("=")
    if not separator or not key:
        raise ValueError(f"la opción {option} espera K=V, no '{text}'")
    return key, value


@app.command(
    "add",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help=(
        "Da de alta un servidor MCP: `tony mcp add <nombre> <url> --agent <agente>` (HTTP) o "
        "`tony mcp add <nombre> -- <comando> <argumentos> --agent <agente>` (stdio). Las opciones "
        "se reconocen aunque vayan después de `--`; para evitar conflictos con las opciones del "
        "propio servidor, pon `--env` antes de `--`. Tras escribir, conecta al servidor y "
        "muestra sus tools."
    ),
)
def add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Nombre del servidor en mcpServers.")],
    agent: Annotated[
        str | None, typer.Option("--agent", help="Agente (carpeta dentro de agents/).")
    ] = None,
    allow: Annotated[
        list[str] | None, typer.Option("--allow", help="Patrón de tools permitidas (repetible).")
    ] = None,
    confirm: Annotated[
        list[str] | None,
        typer.Option("--confirm", help="Tool que exige confirmación (repetible)."),
    ] = None,
    header: Annotated[
        list[str] | None, typer.Option("--header", help="Cabecera HTTP K=V (repetible).")
    ] = None,
    env: Annotated[
        list[str] | None, typer.Option("--env", help="Variable de entorno K=V del servidor.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Sustituye un servidor existente.")
    ] = False,
    agents_dir: Annotated[
        Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
    ] = DEFAULT_AGENTS_DIR,
    config: Annotated[
        Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
    ] = DEFAULT_CONFIG,
) -> None:
    try:
        request = parse_add_tokens(
            [*ctx.args, *_option_tokens(allow, confirm, header, env, force, agent)]
        )
    except ValueError as exc:
        _fail(str(exc), 2)
    if request.agent is None or (request.url is None and request.command is None):
        _fail("Uso: tony mcp add <nombre> <url | -- comando args...> --agent <agente>", 2)
    folder = _agent_folder(agents_dir, request.agent)
    path = folder / "tool" / "tool.json"
    try:
        data = upsert_server(
            read_tool_json(path),
            name,
            request.server(),
            request.allow,
            request.confirm,
            request.force,
        )
    except ToolJsonError as exc:
        _fail(str(exc), 1)
    write_tool_json(path, data)
    typer.echo(f"Servidor '{name}' guardado en {path}")
    asyncio.run(_report_connection(name, folder, _settings(config)))


def _option_tokens(
    allow: list[str] | None,
    confirm: list[str] | None,
    header: list[str] | None,
    env: list[str] | None,
    force: bool,
    agent: str | None,
) -> list[str]:
    tokens: list[str] = []
    for option, values in (
        ("--allow", allow),
        ("--confirm", confirm),
        ("--header", header),
        ("--env", env),
    ):
        for value in values or []:
            tokens += [option, value]
    if force:
        tokens.append("--force")
    if agent is not None:
        tokens += ["--agent", agent]
    return tokens


async def _report_connection(name: str, folder: Path, settings: TonySettings) -> None:
    try:
        spec = load_agent(folder, settings, load_env(DEFAULT_CONFIG.parent / ".env"))
    except AgentLoadError as exc:
        typer.echo(f"Aviso: no se pudo conectar con '{name}': {exc.message}", err=True)
        return
    manager = _manager_factory()(settings)
    try:
        await manager.start(spec.tools, server_filter=[name])
        status = manager.status().get(name)
    finally:
        await manager.stop()
    if status is None or status.state != "ready":
        error = status.error if status is not None else "servidor no declarado"
        typer.echo(f"Aviso: no se pudo conectar con '{name}': {error}", err=True)
        return
    typer.echo(f"{name}: {status.tool_count} tools (allow: {_allow_text(spec, name)})")


@app.command("remove", help="Elimina un servidor MCP de mcpServers conservando el resto.")
def remove(
    name: Annotated[str, typer.Argument(help="Nombre del servidor a eliminar.")],
    agent: Annotated[str, typer.Option("--agent", help="Agente (carpeta dentro de agents/).")],
    agents_dir: Annotated[
        Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
    ] = DEFAULT_AGENTS_DIR,
) -> None:
    path = _agent_folder(agents_dir, agent) / "tool" / "tool.json"
    try:
        data = remove_server(read_tool_json(path), name)
    except ToolJsonError as exc:
        _fail(str(exc), 1)
    write_tool_json(path, data)
    typer.echo(f"Servidor '{name}' eliminado de {path}")


@app.command(
    "list",
    help="Lista los servidores MCP de cada agente y subagente, conectando para ver su estado.",
)
def list_servers(
    agent: Annotated[
        str | None, typer.Option("--agent", help="Limita el listado a un agente.")
    ] = None,
    no_connect: Annotated[
        bool, typer.Option("--no-connect", help="No conecta: solo lee la configuración.")
    ] = False,
    agents_dir: Annotated[
        Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
    ] = DEFAULT_AGENTS_DIR,
    config: Annotated[
        Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
    ] = DEFAULT_CONFIG,
) -> None:
    settings = _settings(config)
    loaded = load_all(agents_dir, settings, load_env(config.parent / ".env"))
    if agent is not None:
        if agent not in loaded:
            _fail(f"No existe el agente '{agent}' en {agents_dir}", 2)
        loaded = {agent: loaded[agent]}
    rows = asyncio.run(_rows(loaded, settings, connect=not no_connect))
    typer.echo(render_table(COLUMNS, rows))


async def _rows(
    loaded: dict[str, AgentSpec | AgentLoadError], settings: TonySettings, connect: bool
) -> list[list[str]]:
    rows: list[list[str]] = []
    for name, spec in loaded.items():
        if isinstance(spec, AgentLoadError):
            rows.append([name, "✗ " + spec.message, NONE, NONE, NONE, NONE, NONE])
            continue
        rows += await _agent_rows(name, spec, settings, connect)
        for child_name, child in spec.subagents.items():
            rows += await _agent_rows(f"{name}/{child_name}", child, settings, connect)
    return rows


async def _agent_rows(
    label: str, spec: AgentSpec, settings: TonySettings, connect: bool
) -> list[list[str]]:
    statuses: dict[str, Any] = {}
    if connect and spec.tools.mcpServers:
        manager = _manager_factory()(settings)
        try:
            await manager.start(spec.tools)
            statuses = manager.status()
        finally:
            await manager.stop()
    rows = []
    for server_name, server in spec.tools.mcpServers.items():
        status = statuses.get(server_name)
        rows.append(
            [
                label,
                server_name,
                "http" if isinstance(server, HttpServer) else "stdio",
                status.state if status else NONE,
                str(status.tool_count) if status else NONE,
                _allow_text(spec, server_name),
                ", ".join(c for c in spec.tools.confirm if c.startswith(f"{server_name}.")) or NONE,
            ]
        )
    return rows


def _allow_text(spec: AgentSpec, server: str) -> str:
    if spec.tools.allow is None:
        return ALL
    own = [p for p in spec.tools.allow if p.startswith(f"{server}.") or p.startswith("*")]
    return ", ".join(own) if own else "ninguna"


def _agent_folder(agents_dir: Path, agent: str) -> Path:
    folder = agents_dir / agent
    if not folder.is_dir():
        _fail(f"No existe el agente '{agent}' en {agents_dir}", 2)
    return folder


def _settings(config: Path) -> TonySettings:
    try:
        return load_settings(config)
    except ConfigError as exc:
        _fail(f"Configuración inválida en {config}: {exc}", 2)


def _manager_factory() -> ManagerFactory:
    from tony.apps.cli import main

    return main.manager_factory


def _fail(message: str, code: int):
    typer.echo(message, err=True)
    raise typer.Exit(code)
