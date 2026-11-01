import asyncio
from collections.abc import Callable

import typer
from pydantic import ValidationError

from tony.core.config.errors import DefinitionError
from tony.core.config.secrets import resolve_home
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.claude_engine import ClaudeEngine
from tony.core.orchestrator.ports import ModelEngine
from tony.core.orchestrator.runner import NotWorkerError, RunDeps, run_task

USAGE_ERROR = 2
TASK_FAILED = 1


def create_app(engine_factory: Callable[[], ModelEngine] = ClaudeEngine) -> typer.Typer:
    app = typer.Typer(help="Tony: asistente personal local.", no_args_is_help=True)

    @app.callback()
    def main() -> None:
        """Tony: asistente personal local."""

    @app.command()
    def run(
        agent: str = typer.Argument(help="Worker agent folder name, e.g. viernes."),
        task: str = typer.Argument(help="Task objective, sent as `objetivo`."),
    ) -> None:
        """Run a worker agent on a task and print the structured JSON result."""
        try:
            request = TaskRequest(objetivo=task)
            deps = RunDeps(root=resolve_home(), engine=engine_factory())
            result = asyncio.run(run_task(agent, request, deps))
        except (ValidationError, DefinitionError, NotWorkerError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        typer.echo(result.model_dump_json())
        if result.errores:
            raise typer.Exit(TASK_FAILED)

    return app


app = create_app()
