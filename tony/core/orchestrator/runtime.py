import asyncio
import os
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import ChangeStream, live_config
from tony.core.config.secrets import Variables, load_variables
from tony.core.config.settings import load_config
from tony.core.config.watcher import watch_config
from tony.core.events import core_events
from tony.core.events.core_events import MaskingPublisher, Publisher
from tony.core.guard.broker import ConfirmationBroker
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import load_policy
from tony.core.guard.session import AuthStatus, EdithSession, SessionGate
from tony.core.loader.agent import AgentDefinition
from tony.core.mcp.manager import McpManager
from tony.core.memory.history import HistoryStore
from tony.core.orchestrator.agents import resolve_slots
from tony.core.orchestrator.commands import (
    Cancel,
    Command,
    Confirm,
    InvalidCommand,
    SendMessage,
    SetMode,
    Stop,
    Unlock,
    parse_command,
)
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.front_tools import WAITING_AFTER_S
from tony.core.orchestrator.natives import NATIVE_TOOLS
from tony.core.orchestrator.ports import ChatEngine, ModelEngine
from tony.core.orchestrator.runner import RunDeps, WordingFactory


class DesktopPinPrompt:
    """PinPrompt for the desktop: publishes the auth state and waits for the next unlock."""

    def __init__(self, publish: Publisher) -> None:
        self._publish = publish
        self._waiting: asyncio.Future[str | None] | None = None

    async def request(self, status: AuthStatus) -> str | None:
        self._publish(core_events.auth(*status))
        self._waiting = asyncio.get_running_loop().create_future()
        try:
            return await self._waiting
        finally:
            self._waiting = None

    def answer(self, pin: str | None) -> bool:
        if self._waiting is None or self._waiting.done():
            return False
        self._waiting.set_result(pin)
        return True


class _DiscardSink:
    def emit(self, event: dict[str, Any]) -> None:
        return None


class CoreRuntime:
    """The desktop core: JSON commands in, core events out, one front-agent turn at a time.

    Every failure is published as an `error` event; nothing a command does stops the loop.
    """

    def __init__(
        self,
        root: Path,
        publish: Publisher,
        *,
        chat_engine: ChatEngine,
        engine: ModelEngine,
        wording: WordingFactory | None = None,
        environ: Mapping[str, str] = os.environ,
        monotonic: Callable[[], float] = time.monotonic,
        waiting_after_s: float = WAITING_AFTER_S,
        changes: ChangeStream = watch_config,
    ) -> None:
        self._root = root
        self._publish = publish
        self._chat_engine = chat_engine
        self._engine = engine
        self._wording = wording
        self._environ = environ
        self._monotonic = monotonic
        self._waiting_after_s = waiting_after_s
        self._changes = changes
        self._stop_watching = asyncio.Event()
        self._commands: asyncio.Queue[Any] = asyncio.Queue()
        self._turns: asyncio.Queue[str] = asyncio.Queue()
        self._background: list[asyncio.Task[None]] = []
        self._turn: asyncio.Task[str | None] | None = None
        self._startup_error = "the core did not start"
        self.conversation: Conversation | None = None
        self.history: HistoryStore | None = None

    def submit(self, raw: Any) -> None:
        self._commands.put_nowait(raw)

    async def serve(self) -> None:
        self._start()
        try:
            while True:
                raw = await self._commands.get()
                try:
                    command = parse_command(raw)
                except InvalidCommand as error:
                    self._publish(core_events.error(error.command_type, str(error)))
                    continue
                if isinstance(command, Stop):
                    return
                try:
                    self._dispatch(command)
                except Exception as error:
                    self._publish(core_events.error(command.type, _describe(error)))
        finally:
            await self._shutdown()

    def _start(self) -> None:
        try:
            config = load_config(self._root)
            slots = resolve_slots(self._root, config)
            policy = load_policy(self._root, config.guard)
        except Exception as error:
            self._startup_error = _describe(error)
            self._publish(core_events.error("startup", self._startup_error))
            return
        variables = load_variables(self._root, self._environ)
        masker = SecretMasker(variables.env_file_values.values())
        self._publish = MaskingPublisher(masker, self._publish)
        self.broker = ConfirmationBroker(self._root, config.guard, self._publish)
        self.session = EdithSession(policy.auth, PinStore(self._root), monotonic=self._monotonic)
        live = live_config(
            self._root,
            config.guard,
            policy,
            native_tools=NATIVE_TOOLS.keys(),
            environ=self._environ,
            publish=self._publish,
        )
        self.pin_prompt = DesktopPinPrompt(self._publish)
        gate = SessionGate(
            self.session,
            self.pin_prompt,
            timeout_s=policy.limits.confirm_timeout_s,
            on_change=lambda status: self._publish(core_events.auth(*status)),
        )
        deps = RunDeps(
            root=self._root,
            engine=self._engine,
            confirmer=self.broker,
            wording=self._wording,
            environ=self._environ,
            monotonic=self._monotonic,
            publish=self._publish,
            policy_source=live.policy,
            tool_specs=live.tools,
        )
        self.history = HistoryStore(self._root, masker)
        self.conversation = Conversation(
            slots=slots,
            config=config,
            deps=deps,
            chat_engine=self._chat_engine,
            gate=gate,
            history=self.history,
            conversation_id=uuid.uuid4().hex,
            waiting_after_s=self._waiting_after_s,
        )
        self._publish(core_events.auth(*self.session.status))
        self._publish(core_events.reply_mode(self.conversation.reply_mode()))
        self._background += [
            asyncio.create_task(self._probe([slots.front, slots.worker], variables, masker)),
            asyncio.create_task(self._answer_turns()),
            asyncio.create_task(
                live.reloader.run(self._changes(self._root, config.guard, self._stop_watching))
            ),
        ]

    def _dispatch(self, command: Command) -> None:
        if self.conversation is None:
            raise RuntimeError(f"the core is not ready: {self._startup_error}")
        if isinstance(command, SendMessage):
            self._turns.put_nowait(command.text)
        elif isinstance(command, Confirm):
            self.broker.answer(command.task_id, command.decision)
        elif isinstance(command, Cancel):
            self._cancel_turn()
        elif isinstance(command, SetMode):
            self.conversation.preferences.set_reply_mode(command.mode)
            self._publish(core_events.reply_mode(command.mode))
        elif isinstance(command, Unlock):
            self._unlock(command.pin)

    def _unlock(self, pin: str | None) -> None:
        if self.pin_prompt.answer(pin):
            return
        status = self.session.cancel() if pin is None else self.session.attempt(pin)
        self._publish(core_events.auth(*status))

    def _cancel_turn(self) -> None:
        self.broker.cancel()
        if self._turn is not None:
            self._turn.cancel()

    async def _answer_turns(self) -> None:
        assert self.conversation is not None
        while True:
            text = await self._turns.get()
            self._turn = asyncio.create_task(self.conversation.handle(text))
            [outcome] = await asyncio.gather(self._turn, return_exceptions=True)
            self._turn = None
            if isinstance(outcome, Exception):
                self._publish(core_events.error("send_message", _describe(outcome)))

    async def _probe(
        self, agents: list[AgentDefinition], variables: Variables, masker: SecretMasker
    ) -> None:
        for agent in agents:
            if not agent.tools.mcp_servers:
                continue
            try:
                async with McpManager(
                    agent.tools,
                    variables=variables,
                    masker=masker,
                    sink=_DiscardSink(),
                    log_dir=self._root / "logs" / "mcp",
                    on_status=self._status_publisher(agent.name),
                ):
                    pass
            except Exception as error:
                self._publish(core_events.error(f"mcp.{agent.name}", _describe(error)))

    def _status_publisher(self, agent: str) -> Callable[[str, Any], None]:
        def publish(server: str, status: Any) -> None:
            self._publish(core_events.mcp_status(agent, server, up=status.up, reason=status.reason))

        return publish

    async def _shutdown(self) -> None:
        self._stop_watching.set()
        if self._turn is not None:
            self._turn.cancel()
        for task in self._background:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*self._background, return_exceptions=True)
        if self.history is not None:
            self.history.close()


def _describe(error: BaseException) -> str:
    return str(error) or type(error).__name__
