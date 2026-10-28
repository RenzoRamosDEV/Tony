"""`tony agents` (inventory) and `tony agents show <name>` (resolved spec without secrets)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from tony.apps.cli.render import render_table
from tony.core.config import ConfigError, TonySettings, load_env, load_settings
from tony.core.loader import AgentLoadError, AgentSpec, load_all
from tony.core.logging import redact

app = typer.Typer(
    help="Inventario de agentes y subagentes; `show` imprime el AgentSpec resuelto en YAML.",
    invoke_without_command=True,
)

DEFAULT_AGENTS_DIR = Path("agents")
DEFAULT_CONFIG = Path("config/tony.yaml")
COLUMNS = ("nombre", "rol", "modelo", "skills", "MCP", "nativas")
INDENT = "  "
BROKEN = "✗"
AgentsDirOption = Annotated[
    Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
]
ConfigOption = Annotated[
    Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
]


@app.callback(help="Lista los agentes del directorio y, indentados, sus subagentes.")
def agents(
    ctx: typer.Context,
    agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR,
    config: ConfigOption = DEFAULT_CONFIG,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(render_table(COLUMNS, render_agents_rows(_load(agents_dir, config))))


@app.command(
    "show",
    help="Imprime en YAML el AgentSpec resuelto (sin secretos) de <agente> o <agente>/<subagente>.",
)
def show(
    name: Annotated[str, typer.Argument(help="Agente o agente/subagente.")],
    agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR,
    config: ConfigOption = DEFAULT_CONFIG,
) -> None:
    agent, _, child = name.partition("/")
    spec = _load(agents_dir, config).get(agent)
    if spec is None:
        _fail(f"No existe el agente '{agent}' en {agents_dir}")
    if isinstance(spec, AgentLoadError):
        _fail(f"No se pudo cargar el agente '{agent}': {spec.message}")
    if child:
        spec = spec.subagents.get(child)
        if spec is None:
            _fail(f"No existe el subagente '{child}' de '{agent}'")
    typer.echo(spec_to_yaml(spec), nl=False)


def render_agents_rows(loaded: dict[str, AgentSpec | AgentLoadError]) -> list[list[str]]:
    rows: list[list[str]] = []
    for name, spec in loaded.items():
        if isinstance(spec, AgentLoadError):
            rows.append(_note(f"{BROKEN} {name}: {spec.message}"))
            continue
        rows.append(_row(name, spec))
        rows.extend(_problem_rows(spec, INDENT))
        for child_name, child in spec.subagents.items():
            rows.append(_row(INDENT + child_name, child))
            rows.extend(_problem_rows(child, INDENT * 2))
    return rows


def _row(label: str, spec: AgentSpec) -> list[str]:
    return [
        label,
        spec.role,
        spec.model,
        str(len(spec.skills)),
        str(len(spec.tools.mcpServers)),
        ", ".join(spec.tools.native) or "-",
    ]


def _problem_rows(spec: AgentSpec, indent: str) -> list[list[str]]:
    rows = [_note(f"{indent}{BROKEN} skill {error}") for error in spec.skill_errors]
    rows += [
        _note(f"{indent}{BROKEN} subagente {name}: {error}")
        for name, error in spec.subagent_errors.items()
    ]
    return rows


def _note(text: str) -> list[str]:
    return [text, *[""] * (len(COLUMNS) - 1)]


def spec_to_yaml(spec: AgentSpec) -> str:
    data = redact(spec_to_dict(spec), spec.all_secrets())
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def spec_to_dict(spec: AgentSpec) -> dict[str, Any]:
    data = spec.model_dump(exclude={"secrets", "path", "skills", "subagents"})
    data["skills"] = [
        {"name": s.name, "description": s.description, "triggers": s.triggers} for s in spec.skills
    ]
    data["subagents"] = {name: spec_to_dict(child) for name, child in spec.subagents.items()}
    return data


def _load(agents_dir: Path, config: Path) -> dict[str, AgentSpec | AgentLoadError]:
    try:
        settings: TonySettings = load_settings(config)
    except ConfigError as exc:
        _fail(f"Configuración inválida en {config}: {exc}")
    if not agents_dir.is_dir():
        _fail(f"No existe el directorio de agentes {agents_dir}")
    return load_all(agents_dir, settings, load_env(config.parent / ".env"))


def _fail(message: str):
    typer.echo(message, err=True)
    raise typer.Exit(2)
