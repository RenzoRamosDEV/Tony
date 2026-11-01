import asyncio
import sys
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import TextIO

from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import ChangeStream, live_config
from tony.core.config.secrets import load_variables
from tony.core.config.settings import TonyConfig
from tony.core.config.watcher import watch_config
from tony.core.events.core_events import Event
from tony.core.guard.confirm import ConsoleLines, thread_line_reader
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import Policy
from tony.core.guard.session import AuthStatus, EdithSession, SessionGate
from tony.core.memory.history import HistoryStore
from tony.core.orchestrator.agents import AgentSlots
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.ports import ChatEngine
from tony.core.orchestrator.runner import RunDeps

EXIT_COMMAND = "/salir"
PIN_COMMAND = "/pin"
NO_LOCK_MESSAGE = (
    "Edith: no hay PIN configurado; modo solo conversación. Ejecute `tony pin set` para "
    "permitir tareas delegadas."
)
PIN_PROMPT = "PIN de Edith (vacío para cancelar): "


class ChatPrinter:
    """Publisher for the terminal: streams the front agent's reply line by line."""

    def __init__(self, out: TextIO | None = None, err: TextIO | None = None) -> None:
        self._out = out
        self._err = err
        self._open = False

    def __call__(self, event: Event) -> None:
        kind = event["type"]
        if kind == "token":
            self._token(event["agent"], event["text"])
        elif kind == "progress":
            self._line(f"{event['agent'].title()}: {event['text']}")
        elif kind == "result" and event["scope"] == "turn":
            self._finish(event["agent"], event["text"])
        elif kind == "error":
            self._close()
            print(f"tony: {event['message']}", file=self._err or sys.stderr)

    def _token(self, agent: str, text: str) -> None:
        out = self._out or sys.stdout
        if not self._open:
            out.write(f"{agent.title()}: ")
            self._open = True
        out.write(text)
        out.flush()

    def _finish(self, agent: str, text: str) -> None:
        if self._open:
            self._close()
        else:
            self._line(f"{agent.title()}: {text}")

    def _line(self, text: str) -> None:
        self._close()
        print(text, file=self._out or sys.stdout, flush=True)

    def _close(self) -> None:
        if self._open:
            print(file=self._out or sys.stdout, flush=True)
            self._open = False


class TerminalPinPrompt:
    """Asks the PIN with hidden input; an empty entry or end of input cancels."""

    def __init__(self, getpass: Callable[[str], str], err: TextIO | None = None) -> None:
        self._read = thread_line_reader(lambda: _hidden(getpass))
        self._err = err

    async def request(self, status: AuthStatus) -> str | None:
        err = self._err or sys.stderr
        if status.reason == "wrong_pin":
            print("Edith: PIN incorrecto.", file=err)
        if status.retry_in_s:
            print(f"Edith: espere {status.retry_in_s} s.", file=err)
            await asyncio.sleep(status.retry_in_s)
        return await self._read() or None


def _hidden(getpass: Callable[[str], str]) -> str | None:
    try:
        return getpass(PIN_PROMPT)
    except EOFError:
        return None


async def run_chat(
    *,
    slots: AgentSlots,
    config: TonyConfig,
    policy: Policy,
    deps: RunDeps,
    chat_engine: ChatEngine,
    console: ConsoleLines,
    getpass: Callable[[str], str],
    changes: ChangeStream = watch_config,
) -> None:
    live = live_config(
        deps.root,
        config.guard,
        policy,
        native_tools=deps.native.keys(),
        environ=deps.environ,
        publish=deps.publish,
    )
    deps = replace(deps, policy_source=live.policy, tool_specs=live.tools)
    stop = asyncio.Event()
    reloader = asyncio.create_task(live.reloader.run(changes(deps.root, config.guard, stop)))
    session = EdithSession(policy.auth, PinStore(deps.root))
    gate = SessionGate(
        session, TerminalPinPrompt(getpass), timeout_s=policy.limits.confirm_timeout_s
    )
    variables = load_variables(deps.root, deps.environ)
    history = HistoryStore(deps.root, SecretMasker(variables.env_file_values.values()))
    conversation = Conversation(
        slots=slots,
        config=config,
        deps=deps,
        chat_engine=chat_engine,
        gate=gate,
        history=history,
        conversation_id=uuid.uuid4().hex,
    )
    try:
        if session.status.reason == "no_lock_file":
            print(NO_LOCK_MESSAGE, file=sys.stderr)
        elif not session.unlocked:
            await gate.ensure_unlocked()
        while (line := await console.next()) is not None:
            text = line.strip()
            if text == EXIT_COMMAND:
                break
            if text == PIN_COMMAND:
                await gate.request_unlock()
            elif text:
                await conversation.handle(text)
    finally:
        stop.set()
        reloader.cancel()
        await asyncio.gather(reloader, return_exceptions=True)
        history.close()
