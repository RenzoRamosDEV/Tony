import asyncio
import getpass as getpass_module
import sys
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated

import typer
from pydantic import ValidationError

from tony.apps.cli.chat import ChatPrinter, run_chat
from tony.core.config.errors import DefinitionError
from tony.core.config.secrets import resolve_home
from tony.core.config.settings import load_config
from tony.core.events.messages import TaskRequest
from tony.core.guard.audit import AUDIT_FILE, AuditLine, read_audit, select_lines
from tony.core.guard.claude_wording import ClaudeWording
from tony.core.guard.confirm import CliConfirmer, ConsoleLines, thread_line_reader
from tony.core.guard.pin import LOCK_FILE, MIN_PIN_LENGTH, PinStore
from tony.core.guard.policy import load_policy
from tony.core.orchestrator.agents import AgentSlots, resolve_slots
from tony.core.orchestrator.claude_engine import ClaudeEngine
from tony.core.orchestrator.ports import ChatEngine, ModelEngine
from tony.core.orchestrator.runner import NotWorkerError, RunDeps, WordingFactory, run_task

EDITH_PREFIX = "Edith: "
USAGE_ERROR = 2
TASK_FAILED = 1
AGENT_COLUMNS = ("slot", "agent", "role", "model", "voice")
AUDIT_COLUMNS = ("ts", "agent", "tool", "verdict", "rule", "user_decision")


class VerdictFilter(StrEnum):
    allow = "allow"
    confirm = "confirm"
    deny = "deny"


def stdin_readline() -> Callable[[], str]:
    return sys.stdin.readline


def create_app(
    engine_factory: Callable[[], ModelEngine] = ClaudeEngine,
    wording_factory: WordingFactory | None = ClaudeWording,
    readline_factory: Callable[[], Callable[[], str | None]] = stdin_readline,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    getpass: Callable[[str], str] = getpass_module.getpass,
    chat_engine_factory: Callable[[], ChatEngine] = ClaudeEngine,
    console_factory: Callable[[], ConsoleLines] = lambda: ConsoleLines(sys.stdin),
) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True)
    pin_app = typer.Typer(no_args_is_help=True, help="Manage Edith's PIN.")
    app.add_typer(pin_app, name="pin")

    @pin_app.command("set")
    def pin_set() -> None:
        """Ask the PIN twice and store its argon2 hash in config/edith.lock."""
        first = getpass("PIN: ")
        second = getpass("Repeat the PIN: ")
        if first != second:
            typer.echo("tony: the PIN entries do not match", err=True)
            raise typer.Exit(USAGE_ERROR)
        if len(first) < MIN_PIN_LENGTH:
            typer.echo(f"tony: the PIN must have at least {MIN_PIN_LENGTH} characters", err=True)
            raise typer.Exit(USAGE_ERROR)
        PinStore(resolve_home()).set(first)
        typer.echo(f"PIN stored in {LOCK_FILE}")

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
            deps = RunDeps(
                root=resolve_home(),
                engine=engine_factory(),
                confirmer=CliConfirmer(thread_line_reader(readline_factory())),
                wording=wording_factory,
            )
            result = asyncio.run(run_task(agent, request, deps))
        except (ValidationError, DefinitionError, NotWorkerError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        typer.echo(result.model_dump_json())
        if result.errores:
            raise typer.Exit(TASK_FAILED)

    @app.command()
    def audit(
        today: Annotated[
            bool, typer.Option("--today", help="Only lines of the current local date.")
        ] = False,
        verdict: Annotated[
            VerdictFilter | None, typer.Option(help="Only lines with this verdict.")
        ] = None,
    ) -> None:
        """Print Edith's audit trail (logs/audit.jsonl) as a table, oldest first."""
        lines, malformed = read_audit(resolve_home())
        if malformed:
            typer.echo(f"tony: skipped {malformed} malformed lines in {AUDIT_FILE}", err=True)
        selected = select_lines(
            lines,
            verdict=verdict.value if verdict else None,
            local_day_of=now() if today else None,
        )
        typer.echo(audit_table(selected))

    @app.command()
    def chat() -> None:
        """Talk to the front agent; /pin asks Edith's PIN again, /salir ends the chat."""
        root = resolve_home()
        try:
            config = load_config(root)
            slots = resolve_slots(root, config)
            policy = load_policy(root, config.guard)
        except DefinitionError as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        console = console_factory()
        deps = RunDeps(
            root=root,
            engine=engine_factory(),
            confirmer=CliConfirmer(console.next, prefix=EDITH_PREFIX),
            wording=wording_factory,
            publish=ChatPrinter(),
        )
        asyncio.run(
            run_chat(
                slots=slots,
                config=config,
                policy=policy,
                deps=deps,
                chat_engine=chat_engine_factory(),
                console=console,
                getpass=getpass,
            )
        )

    @app.command()
    def agents() -> None:
        """List the front, worker and guard agents of config/tony.yaml."""
        root = resolve_home()
        try:
            slots = resolve_slots(root, load_config(root))
        except DefinitionError as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        typer.echo(agents_table(slots))

    return app


def agents_table(slots: AgentSlots) -> str:
    named = (("front", slots.front), ("worker", slots.worker), ("guard", slots.guard))
    return table(
        AGENT_COLUMNS,
        [
            (slot, agent.name, agent.spec.role, agent.spec.model, agent.spec.voice.tts)
            for slot, agent in named
        ],
    )


def audit_table(lines: list[AuditLine]) -> str:
    return table(
        AUDIT_COLUMNS, [tuple(_cell(line, column) for column in AUDIT_COLUMNS) for line in lines]
    )


def table(columns: tuple[str, ...], body: list[tuple[str, ...]]) -> str:
    rows = [columns, *body]
    widths = [max(len(row[index]) for row in rows) for index in range(len(columns))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def _cell(line: AuditLine, column: str) -> str:
    value = line.get(column)
    return "-" if value is None else str(value)


app = create_app()
