import asyncio
import getpass as getpass_module
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import click
import typer
from pydantic import ValidationError
from typer.core import TyperCommand

from tony.apps.cli.chat import ChatPrinter, run_chat
from tony.apps.cli.recover_commands import add_recover_app
from tony.apps.cli.routines_commands import add_routines_app
from tony.apps.cli.shared import (
    TASK_FAILED,
    USAGE_ERROR,
    read_journal,
    report_result,
    running_journal,
    table,
    usage_error,
)
from tony.core.clarification.cli import CliClarifier
from tony.core.config.errors import DefinitionError
from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import ChangeStream
from tony.core.config.secrets import ENV_FILE, SECRET_NAME, load_variables, resolve_home
from tony.core.config.settings import load_config
from tony.core.config.watcher import watch_config
from tony.core.diagnostics.checks import Check, run_checks
from tony.core.diagnostics.report import exit_code, format_report
from tony.core.events.messages import TaskRequest
from tony.core.guard.allow_always import revoke_allow_always
from tony.core.guard.audit import AUDIT_FILE, AuditLine, read_audit, select_lines
from tony.core.guard.caching_wording import cached_wording_factory
from tony.core.guard.claude_wording import ClaudeWording
from tony.core.guard.confirm import CliConfirmer, ConsoleLines, thread_line_reader
from tony.core.guard.inspector import (
    CaseResult,
    MalformedCases,
    explain,
    grants,
    parse_cases,
    simulate,
)
from tony.core.guard.pin import LOCK_FILE, MIN_PIN_LENGTH, PinStore
from tony.core.guard.policy import load_policy, load_policy_with_version
from tony.core.loader.tool_json import ToolSpec, agent_folder, load_tool_spec, tool_json_keys
from tony.core.loader.tool_json_writer import add_server
from tony.core.mcp.manager import McpManager
from tony.core.memory.actions import (
    ACTION_STATES,
    ActionJournal,
    ActionRecord,
)
from tony.core.memory.history import ConversationSummary, HistoryStore
from tony.core.memory.undo import UndoStore
from tony.core.orchestrator.agents import AgentSlots, resolve_slots
from tony.core.orchestrator.claude_engine import ClaudeEngine
from tony.core.orchestrator.natives import NATIVE_TOOLS
from tony.core.orchestrator.ports import ChatEngine, ModelEngine
from tony.core.orchestrator.runner import NotWorkerError, RunDeps, WordingFactory, run_task

EDITH_PREFIX = "Edith: "
AGENT_COLUMNS = ("slot", "agent", "role", "model", "voice")
MCP_COLUMNS = ("agent", "server", "state", "tools")
CONVERSATION_COLUMNS = ("id", "title", "messages", "last")
ACTION_COLUMNS = ("call", "time", "state", "agent", "tool")
NO_ACTIONS = "no actions recorded"
AUDIT_COLUMNS = ("ts", "agent", "tool", "verdict", "rule", "user_decision")


class VerdictFilter(StrEnum):
    allow = "allow"
    confirm = "confirm"
    deny = "deny"


CACHED_CLAUDE_WORDING = cached_wording_factory(ClaudeWording)


def stdin_readline() -> Callable[[], str]:
    return sys.stdin.readline


def create_app(
    engine_factory: Callable[[], ModelEngine] = ClaudeEngine,
    wording_factory: WordingFactory | None = CACHED_CLAUDE_WORDING,
    readline_factory: Callable[[], Callable[[], str | None]] = stdin_readline,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    getpass: Callable[[str], str] = getpass_module.getpass,
    chat_engine_factory: Callable[[], ChatEngine] = ClaudeEngine,
    console_factory: Callable[[], ConsoleLines] = lambda: ConsoleLines(sys.stdin),
    desktop_launcher: Callable[..., object] | None = None,
    change_stream_factory: ChangeStream = watch_config,
    doctor_checks: Callable[[Path], list[Check]] = run_checks,
) -> typer.Typer:
    app = typer.Typer()

    def run_deps(root: Path, journal: ActionJournal) -> RunDeps:
        return RunDeps(
            root=root,
            engine=engine_factory(),
            confirmer=CliConfirmer(thread_line_reader(readline_factory())),
            clarifier=CliClarifier(thread_line_reader(readline_factory())),
            wording=wording_factory,
            journal=journal,
            snapshots=UndoStore(root),
        )

    add_recover_app(app, run_deps=run_deps, now=now)
    add_routines_app(app, now=now)
    pin_app = typer.Typer(no_args_is_help=True, help="Manage Edith's PIN.")
    app.add_typer(pin_app, name="pin")
    mcp_app = typer.Typer(no_args_is_help=True, help="Manage the agents' MCP servers.")
    app.add_typer(mcp_app, name="mcp")
    conversations_app = typer.Typer(no_args_is_help=True, help="Manage stored conversations.")
    app.add_typer(conversations_app, name="conversations")

    actions_app = typer.Typer(no_args_is_help=True, help="Inspect the journal of executed tools.")
    app.add_typer(actions_app, name="actions")

    policy_app = typer.Typer(no_args_is_help=True, help="Inspect and manage Edith's policy.")
    app.add_typer(policy_app, name="policy")

    @policy_app.command("explain")
    def policy_explain(
        tool: Annotated[str, typer.Argument(help="Tool id, e.g. shell.run.")],
        args: Annotated[
            str, typer.Option("--args", help="Tool arguments as a JSON object.")
        ] = "{}",
    ) -> None:
        """Show the verdict, rule and position the policy gives a tool call."""
        root = resolve_home()
        try:
            policy = load_policy(root, load_config(root).guard)
            parsed = json.loads(args)
            if not isinstance(parsed, dict):
                raise UsageError("--args must be a JSON object")
        except (DefinitionError, UsageError, json.JSONDecodeError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        explanation = explain(policy, tool, parsed)
        typer.echo(f"verdict: {explanation.verdict}\nrule: {explanation.rule}")
        if explanation.position is not None:
            typer.echo(f"position: {explanation.position}")

    @policy_app.command("grants")
    def policy_grants() -> None:
        """List the tools Edith was told to allow always."""
        root = resolve_home()
        try:
            granted = grants(load_policy(root, load_config(root).guard))
        except DefinitionError as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        typer.echo("\n".join(granted) if granted else "no allow-always grants")

    @policy_app.command("revoke")
    def policy_revoke(tool: Annotated[str, typer.Argument(help="Tool id of the grant.")]) -> None:
        """Remove the allow-always grant of a tool from the policy."""
        root = resolve_home()
        try:
            removed = revoke_allow_always(root, load_config(root).guard, tool)
        except (DefinitionError, OSError, ValueError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        if not removed:
            typer.echo(f"tony: no allow-always grant for {tool}", err=True)
            raise typer.Exit(TASK_FAILED)
        typer.echo(f"revoked allow-always for {tool}")

    @policy_app.command("simulate")
    def policy_simulate(
        file: Annotated[Path, typer.Argument(help="JSON list of {tool, args, expect}.")],
    ) -> None:
        """Evaluate each case against the policy; exit 1 if any case fails."""
        root = resolve_home()
        try:
            policy = load_policy(root, load_config(root).guard)
            cases = parse_cases(file.read_text(encoding="utf-8"))
        except (DefinitionError, MalformedCases, OSError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        results = simulate(policy, cases)
        for result in results:
            typer.echo(simulation_line(result))
        if not all(result.passed for result in results):
            raise typer.Exit(TASK_FAILED)

    @conversations_app.command("list")
    def conversations_list() -> None:
        """List the most recent conversations, newest first."""
        with open_history(resolve_home()) as history:
            typer.echo(conversations_table(history.list_conversations()))

    @conversations_app.command("search")
    def conversations_search(
        text: Annotated[str, typer.Argument(help="Text to look for, ignoring case.")],
    ) -> None:
        """List the conversations having a message that contains the text."""
        with open_history(resolve_home()) as history:
            typer.echo(conversations_table(history.search_conversations(text)))

    @conversations_app.command("delete")
    def conversations_delete(
        conversation_id: Annotated[str, typer.Argument(metavar="ID", help="Conversation id.")],
    ) -> None:
        """Delete every message of a conversation."""
        with open_history(resolve_home()) as history:
            removed = history.delete_conversation(conversation_id)
        if not removed:
            typer.echo(f"tony: unknown conversation {conversation_id}", err=True)
            raise typer.Exit(USAGE_ERROR)
        typer.echo(f"deleted conversation {conversation_id}")

    @actions_app.command("list")
    def actions_list(
        state: Annotated[
            str | None,
            typer.Option("--state", help=f"Only this state: {', '.join(ACTION_STATES)}."),
        ] = None,
        limit: Annotated[int, typer.Option("--limit", help="Rows to print, newest first.")] = 20,
    ) -> None:
        """List the most recent journaled tool calls, newest first."""
        if state is not None and state not in ACTION_STATES:
            usage_error(f"unknown state '{state}'; valid states: {', '.join(ACTION_STATES)}")
        if limit < 1:
            usage_error("--limit must be at least 1")
        with read_journal(resolve_home()) as journal:
            records = journal.list(state, limit) if journal else []
        typer.echo(actions_table(records) if records else NO_ACTIONS)

    @actions_app.command("show")
    def actions_show(
        call_id: Annotated[str, typer.Argument(metavar="CALL_ID", help="Call id.")],
    ) -> None:
        """Print every field of a journaled tool call."""
        with read_journal(resolve_home()) as journal:
            record = journal.get(call_id) if journal else None
        if record is None:
            usage_error(f"unknown action {call_id}")
        for name, value in asdict(record).items():
            typer.echo(f"{name}: {value}")

    @mcp_app.command("add")
    def mcp_add(
        name: Annotated[str, typer.Argument(help="Server name, e.g. notas.")],
        target: Annotated[str, typer.Argument(help="Command (stdio) or http(s):// URL (HTTP).")],
        agent: Annotated[
            str, typer.Option("--agent", help="Agent or <agent>/<subagent> to extend.")
        ],
        arg: Annotated[
            list[str] | None, typer.Option("--arg", help="Stdio argument (repeatable).")
        ] = None,
        header: Annotated[
            list[str] | None, typer.Option("--header", help="HTTP header K=V (repeatable).")
        ] = None,
        env: Annotated[
            list[str] | None, typer.Option("--env", help="Stdio environment K=V (repeatable).")
        ] = None,
    ) -> None:
        """Add an MCP server to an agent's tool.json (use ${VAR} placeholders for secrets)."""
        try:
            entry = server_entry(target, arg or [], header or [], env or [])
            file = add_server(resolve_home(), agent, name, entry, native_tools=NATIVE_TOOLS)
        except (UsageError, DefinitionError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        for key in literal_secrets(entry):
            typer.echo(
                f"tony: warning: {key} looks like a secret written literally; use a ${{VAR}} "
                f"placeholder defined in {ENV_FILE}",
                err=True,
            )
        typer.echo(f"added {name} to {file}")

    @mcp_app.command("list")
    def mcp_list(
        agent: Annotated[
            str | None, typer.Option("--agent", help="Only this agent or <agent>/<subagent>.")
        ] = None,
    ) -> None:
        """Connect every declared MCP server and print its state and tool count."""
        root = resolve_home()
        try:
            keys = tool_json_keys(root) if agent is None else [_existing_agent(root, agent)]
        except DefinitionError as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        specs, invalid = {}, False
        for key in keys:
            try:
                specs[key] = load_tool_spec(root, key, native_tools=NATIVE_TOOLS)
            except DefinitionError as error:
                typer.echo(f"tony: {error}", err=True)
                invalid = True
        body = asyncio.run(server_rows(root, specs))
        typer.echo(table(MCP_COLUMNS, body))
        if invalid:
            raise typer.Exit(TASK_FAILED)

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

    @app.callback(invoke_without_command=True)
    def main(
        context: typer.Context,
        focus: Annotated[
            bool,
            typer.Option("--focus", help="Raise the running app (or open it) and start listening."),
        ] = False,
    ) -> None:
        """Tony: asistente personal local. Without a command, opens the desktop app."""
        if context.invoked_subcommand is None:
            (desktop_launcher or launch_desktop)(focus=focus)
        elif focus:
            raise typer.BadParameter(
                "--focus can not be combined with a command", param_hint="--focus"
            )

    @app.command()
    def run(
        agent: str = typer.Argument(help="Worker agent folder name, e.g. viernes."),
        task: str = typer.Argument(help="Task objective, sent as `objetivo`."),
    ) -> None:
        """Run a worker agent on a task and print the structured JSON result."""
        try:
            request = TaskRequest(objetivo=task)
            root = resolve_home()
            with running_journal(root) as journal:
                result = asyncio.run(run_task(agent, request, run_deps(root, journal)))
        except (ValidationError, DefinitionError, NotWorkerError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        report_result(result)

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

    @app.command(cls=BareResumeCommand)
    def chat(
        resume: Annotated[
            str | None,
            typer.Option(
                "--resume",
                metavar="[ID]",
                help="Continue conversation ID, or the most recent one when ID is omitted.",
            ),
        ] = None,
    ) -> None:
        """Talk to the front agent; /pin asks Edith's PIN again, /salir ends the chat."""
        root = resolve_home()
        try:
            config = load_config(root)
            slots = resolve_slots(root, config)
            policy, policy_version = load_policy_with_version(root, config.guard)
            conversation_id = None if resume is None else resolve_resume(root, resume)
        except (DefinitionError, UsageError) as error:
            typer.echo(f"tony: {error}", err=True)
            raise typer.Exit(USAGE_ERROR) from error
        console = console_factory()
        deps = RunDeps(
            root=root,
            engine=engine_factory(),
            confirmer=CliConfirmer(console.next, prefix=EDITH_PREFIX),
            clarifier=CliClarifier(console.next),
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
                changes=change_stream_factory,
                conversation_id=conversation_id,
                policy_version=policy_version,
            )
        )

    @app.command()
    def doctor() -> None:
        """Check the installation locally (nothing is started or connected); exit 1 on a fail."""
        checks = doctor_checks(resolve_home())
        typer.echo(format_report(checks))
        raise typer.Exit(exit_code(checks))

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


class BareResumeCommand(TyperCommand):
    """Typer has no optional option value: a bare `--resume` gets an empty value (the latest)."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        args = list(args)
        for index, arg in enumerate(args):
            if arg == "--resume" and (index + 1 == len(args) or args[index + 1].startswith("-")):
                args.insert(index + 1, "")
        return super().parse_args(ctx, args)


class UsageError(Exception):
    pass


@contextmanager
def open_history(root: Path) -> Iterator[HistoryStore]:
    variables = load_variables(root, os.environ)
    history = HistoryStore(root, SecretMasker(variables.env_file_values.values()))
    try:
        yield history
    finally:
        history.close()


def resolve_resume(root: Path, requested: str) -> str:
    """The conversation id to continue: the requested one, or the latest when none was given."""
    with open_history(root) as history:
        if requested:
            if not history.has_conversation(requested):
                raise UsageError(f"unknown conversation {requested}")
            return requested
        latest = history.list_conversations(limit=1)
        if not latest:
            raise UsageError("there is no conversation to resume")
        return latest[0].id


def simulation_line(result: CaseResult) -> str:
    if result.passed:
        return f"pass {result.index} {result.tool}"
    return f"fail {result.index} {result.tool}: expected {result.expected}, got {result.actual}"


def actions_table(records: list[ActionRecord]) -> str:
    return table(
        ACTION_COLUMNS,
        [(r.call_id, r.created_at, r.state, r.agent, r.tool) for r in records],
    )


def conversations_table(conversations: list[ConversationSummary]) -> str:
    return table(
        CONVERSATION_COLUMNS,
        [(c.id, c.title, str(c.message_count), c.last_ts) for c in conversations],
    )


HTTP_PREFIXES = ("http://", "https://")


def server_entry(
    target: str, args: list[str], headers: list[str], env: list[str]
) -> dict[str, Any]:
    """The tool.json entry for a target: HTTP for http(s) URLs, stdio otherwise."""
    if target.startswith(HTTP_PREFIXES):
        _refuse_options(("--arg", args), ("--env", env), transport="an HTTP")
        return _without_empty({"url": target, "headers": _pairs("--header", headers)})
    _refuse_options(("--header", headers), transport="a stdio")
    return _without_empty({"command": target, "args": args, "env": _pairs("--env", env)})


def literal_secrets(entry: dict[str, Any]) -> list[str]:
    pairs: dict[str, str] = {**entry.get("headers", {}), **entry.get("env", {})}
    return [key for key, value in pairs.items() if SECRET_NAME.search(key) and "${" not in value]


def _refuse_options(*options: tuple[str, list[str]], transport: str) -> None:
    for option, values in options:
        if values:
            raise UsageError(f"{option} does not apply to {transport} server")


def _pairs(option: str, items: list[str]) -> dict[str, str]:
    pairs = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise UsageError(f"{option} expects KEY=VALUE")
        pairs[key] = value
    return pairs


def _without_empty(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if value}


def _existing_agent(root: Path, key: str) -> str:
    folder = agent_folder(key)
    if not (root / folder).is_dir():
        raise DefinitionError(folder, None, f"agent folder {folder} does not exist")
    return key


class _Discard:
    def emit(self, event: dict[str, Any]) -> None:
        return None


async def server_rows(root: Path, specs: dict[str, ToolSpec]) -> list[tuple[str, ...]]:
    """One row per declared server: connected, listed and closed one agent at a time."""
    variables = load_variables(root, os.environ)
    masker = SecretMasker(variables.env_file_values.values())
    body: list[tuple[str, ...]] = []
    for key, spec in specs.items():
        async with McpManager(
            spec.model_copy(update={"native": []}),
            variables=variables,
            masker=masker,
            sink=_Discard(),
            log_dir=root / "logs" / "mcp",
        ) as manager:
            counts = Counter(tool.server for tool in manager.tools)
            for server, status in manager.status.items():
                state = "ok" if status.up else f"error: {status.reason}"
                body.append((key, server, state, str(counts[server])))
    return body


def launch_desktop(*, focus: bool) -> None:
    from tony.apps.desktop.app import launch

    raise typer.Exit(launch(resolve_home(), focus=focus))


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


def _cell(line: AuditLine, column: str) -> str:
    value = line.get(column)
    return "-" if value is None else str(value)


app = create_app()
