"""Manage the engine profile selected by agents and subagents."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from tony.apps.cli.agents_cli import (
    DEFAULT_AGENTS_DIR,
    DEFAULT_CONFIG,
    INDENT,
    AgentsDirOption,
    ConfigOption,
)
from tony.apps.cli.render import render_table
from tony.core.config import ConfigError, TonySettings, load_env, load_settings
from tony.core.loader import AgentLoadError, AgentSpec, load_all
from tony.core.loader.agentmd import edit_agent_frontmatter
from tony.core.loader.frontmatter import FrontmatterError

app = typer.Typer(
    help="Gestiona el motor de un agente (claude_sdk, codex_cli, litellm).",
    no_args_is_help=True,
)


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(2)


def _settings(config: Path) -> TonySettings:
    try:
        return load_settings(config)
    except ConfigError as exc:
        _fail(f"Configuración inválida en {config}: {exc}")


def _load(
    agents_dir: Path, config: Path, settings: TonySettings
) -> dict[str, AgentSpec | AgentLoadError]:
    if not agents_dir.is_dir():
        _fail(f"No existe el directorio de agentes {agents_dir}")
    return load_all(agents_dir, settings, load_env(config.parent / ".env"))


def _resolve(loaded: dict[str, AgentSpec | AgentLoadError], name: str) -> AgentSpec:
    candidates = {}
    for parent, spec in loaded.items():
        if isinstance(spec, AgentLoadError):
            if parent == name:
                _fail(f"No se pudo cargar el agente '{name}': {spec.message}")
            continue
        candidates[parent] = spec
        candidates.update(
            {f"{parent}/{child}": child_spec for child, child_spec in spec.subagents.items()}
        )
    if name in candidates:
        return candidates[name]
    matches = [spec for label, spec in candidates.items() if label.rsplit("/", 1)[-1] == name]
    if len(matches) == 1:
        return matches[0]
    if matches:
        _fail(f"Nombre de agente ambiguo '{name}'; usa agente/subagente.")
    _fail(f"No existe el agente '{name}'")


@app.command("set", help="Cambia el motor de un agente o subagente al perfil indicado.")
def set_engine(
    agent: Annotated[str, typer.Argument(help="Nombre del agente o agente/subagente.")],
    profile: Annotated[str, typer.Argument(help="Perfil declarado en engines de tony.yaml.")],
    agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR,
    config: ConfigOption = DEFAULT_CONFIG,
) -> None:
    settings = _settings(config)
    if profile not in settings.engines:
        _fail(
            f"Perfil de motor desconocido '{profile}'. "
            f"Perfiles válidos: {', '.join(settings.engines)}"
        )
    spec = _resolve(_load(agents_dir, config, settings), agent)
    try:
        edit_agent_frontmatter(spec.path / "agent.md", lambda header: {**header, "engine": profile})
    except (FrontmatterError, OSError) as exc:
        _fail(f"No se pudo editar el agente '{agent}': {exc}")
    typer.echo(f"Motor de '{agent}' cambiado a '{profile}'.")


@app.command("list", help="Lista los agentes y subagentes con su motor y tipo resuelto.")
def list_engines(
    agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR,
    config: ConfigOption = DEFAULT_CONFIG,
) -> None:
    settings = _settings(config)
    loaded = _load(agents_dir, config, settings)
    rows = []
    for name, spec in loaded.items():
        if isinstance(spec, AgentLoadError):
            rows.append([f"✗ {name}: {spec.message}", "", ""])
            continue
        rows.append([name, spec.engine, settings.engines[spec.engine].type])
        for child_name, child in spec.subagents.items():
            rows.append([INDENT + child_name, child.engine, settings.engines[child.engine].type])
        for child_name, error in spec.subagent_errors.items():
            rows.append([f"{INDENT}✗ {child_name}: {error}", "", ""])
    typer.echo(render_table(("agente", "motor", "tipo"), rows))
