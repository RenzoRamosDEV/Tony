"""`tony doctor` and `tony config validate`: render check results as ✓/✗/· lines."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

import typer

from tony.core.doctor.checks import (
    CheckResult,
    DoctorPaths,
    Environment,
    exit_code,
    run_checks,
    validate_config,
)

DEFAULT_AGENTS_DIR = Path("agents")
DEFAULT_CONFIG = Path("config/tony.yaml")
MARKERS = {True: "✓", False: "✗", None: "·"}
HINT_PREFIX = "    → "

config_app = typer.Typer(
    help="Comprobaciones de configuración sin red ni procesos.", no_args_is_help=True
)
environment = Environment()

AgentsDirOption = Annotated[
    Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
]
ConfigOption = Annotated[
    Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
]


def doctor(
    offline: Annotated[
        bool, typer.Option("--offline", help="Omite la petición de prueba al modelo.")
    ] = False,
    agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR,
    config: ConfigOption = DEFAULT_CONFIG,
) -> None:
    """Diagnostica la instalación: Python, CLI de Claude, modelo, configuración, agentes,
    skills, variables, node/npx, voz y conexión a cada servidor MCP."""
    paths = DoctorPaths(config_path=config, agents_dir=agents_dir)
    results = asyncio.run(run_checks(paths, environment, offline=offline, connect=True))
    _report(results)


@config_app.command("validate")
def validate(
    agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR, config: ConfigOption = DEFAULT_CONFIG
) -> None:
    """Valida tony.yaml, .env, agentes, subagentes, skills y variables sin conectar a
    ningún MCP ni al modelo."""
    paths = DoctorPaths(config_path=config, agents_dir=agents_dir)
    _report(asyncio.run(validate_config(paths, environment)))


def render_results(results: Iterable[CheckResult]) -> str:
    lines = []
    for result in results:
        detail = f": {result.detail}" if result.detail else ""
        lines.append(f"{MARKERS[result.ok]} {result.name}{detail}")
        if result.failed and result.hint:
            lines.append(f"{HINT_PREFIX}{result.hint}")
    return "\n".join(lines)


def _report(results: list[CheckResult]) -> None:
    typer.echo(render_results(results))
    raise typer.Exit(exit_code(results))
