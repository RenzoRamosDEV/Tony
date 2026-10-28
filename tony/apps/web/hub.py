"""One open chat session per server, one active socket per conversation (design.md D4)."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from tony.apps.web.confirmations import ConfirmationRouter, InvalidConfirmation, WebConfirmGate
from tony.apps.web.protocol import (
    CANCEL,
    CLOSE_GOING_AWAY,
    CLOSE_POLICY_VIOLATION,
    CONFIRM,
    ERROR,
    HELLO,
    HELLO_OK,
    SET_MODE,
    USER_TEXT,
    ClientMessage,
    ConversationStream,
    Envelope,
    OutboundQueue,
)
from tony.apps.web.ws_channel import UsageTracker, WebChannel
from tony.core.channels.bootstrap import ChatRuntime
from tony.core.channels.ports import AssistantReply
from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.orchestrator.clock import Clock
from tony.core.orchestrator.errors import OrchestratorError

WEB_CHANNEL = "web"
TURN_CRASHED = "No pude completar el turno por un error interno: {error}"
HELLO_REQUIRED = "envía hello antes de cualquier otro mensaje"
UNKNOWN_CONVERSATION = "la conversación {} no existe"
SOCKET_BUSY = "la conversación ya tiene un socket activo"
CONVERSATION_BUSY = "hay otra conversación en curso"
HelloDecision = Literal["open", "attach", "switch", "busy_same", "busy_other", "unknown"]


class SocketLike(Protocol):
    async def send_text(self, text: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


@dataclass(frozen=True)
class HubState:
    conversation_id: str | None
    has_socket: bool
    busy: bool


def decide_hello(state: HubState, requested: str | None, exists: bool) -> HelloDecision:
    if requested is not None and not exists:
        return "unknown"
    if state.conversation_id is None:
        return "open"
    if requested == state.conversation_id:
        return "busy_same" if state.has_socket else "attach"
    if state.has_socket or state.busy:
        return "busy_other"
    return "switch"


def error_envelope(code: str, detail: str, conversation_id: str | None = None) -> Envelope:
    return Envelope(
        type=ERROR, seq=0, conversation_id=conversation_id, payload={"code": code, "detail": detail}
    )


class ConversationHub:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.router: ConfirmationRouter | None = None
        self.gate: WebConfirmGate | None = None
        self.usage: UsageTracker | None = None
        self.stream: ConversationStream | None = None
        self.channel: WebChannel | None = None
        self.conversation_id: str | None = None
        self.socket: SocketLike | None = None
        self.turn: asyncio.Task[None] | None = None
        self._emitter: asyncio.Task[None] | None = None
        self._runtime: ChatRuntime | None = None

    def gate_factory(self, settings: TonySettings, front: AgentSpec) -> WebConfirmGate:
        limits = settings.limits
        self.router = ConfirmationRouter(
            now=self._clock.monotonic, timeout_s=limits.confirm_timeout_s
        )
        self.usage = UsageTracker(limits.token_alert)
        self.gate = WebConfirmGate(self.router, None, limits.confirm_timeout_s, self._clock)
        return self.gate

    def bind(self, runtime: ChatRuntime) -> None:
        self._runtime = runtime

    @property
    def runtime(self) -> ChatRuntime:
        assert self._runtime is not None, "bind() must run before serving"
        return self._runtime

    @property
    def turn_in_progress(self) -> bool:
        return self.turn is not None and not self.turn.done()

    @property
    def state(self) -> HubState:
        session = self.runtime.session
        busy = self.turn_in_progress or (session is not None and session.has_active_task)
        return HubState(self.conversation_id, self.socket is not None, busy)

    async def dispatch(self, socket: SocketLike, message: ClientMessage) -> None:
        payload = message.payload
        if message.type == HELLO:
            await self.hello(
                socket, payload.get("conversation_id"), int(payload.get("last_seq") or 0)
            )
        elif socket is not self.socket:
            await self._error(
                socket, "hello_required", "envía hello antes de cualquier otro mensaje"
            )
        elif message.type == USER_TEXT:
            await self.user_text(str(payload.get("text") or ""))
        elif message.type == CONFIRM:
            await self.confirm(
                str(payload.get("confirmation_id") or ""), bool(payload.get("approved"))
            )
        elif message.type == CANCEL:
            await self.cancel(str(payload.get("task_id") or ""))
        elif message.type == SET_MODE:
            await self.set_mode(str(payload.get("reply_mode") or ""))

    async def hello(self, socket: SocketLike, requested: str | None, last_seq: int) -> None:
        exists = requested is not None and self.runtime.memory.conversations.has_conversation(
            requested
        )
        decision = decide_hello(self.state, requested, exists)
        if decision == "unknown":
            await self._error(
                socket, "unknown_conversation", f"la conversación {requested} no existe"
            )
        elif decision == "busy_same":
            await self._error(
                socket, "conversation_busy", "la conversación ya tiene un socket activo"
            )
            await socket.close(CLOSE_POLICY_VIOLATION)
        elif decision == "busy_other":
            await self._error(socket, "conversation_busy", "hay otra conversación en curso")
        else:
            if decision == "switch":
                await self._close_conversation()
            if decision in ("open", "switch"):
                await self._open_conversation(requested)
            await self._attach(socket, last_seq)

    def detach(self, socket: SocketLike) -> None:
        if socket is not self.socket:
            return
        self.socket = None
        if self.stream is not None:
            self.stream.detach()
        emitter, self._emitter = self._emitter, None
        if emitter is not None and emitter is not asyncio.current_task():
            emitter.cancel()

    async def user_text(self, text: str) -> None:
        assert self.socket is not None
        if self.turn_in_progress:
            await self._error(self.socket, "turn_in_progress", "espera a que termine la respuesta")
            return
        if not text.strip():
            await self._error(self.socket, "empty_text", "el mensaje está vacío")
            return
        self.turn = asyncio.create_task(self._run_turn(text))

    async def confirm(
        self, confirmation_id: str, approved: bool, task_id: str | None = None
    ) -> None:
        assert self.router is not None
        try:
            await self.router.resolve(confirmation_id, approved, task_id)
        except InvalidConfirmation as exc:
            if self.socket is not None:
                await self._error(self.socket, exc.code, exc.detail)

    async def cancel(self, task_id: str) -> None:
        try:
            await self.cancel_task(task_id)
        except OrchestratorError as exc:
            if self.socket is not None:
                await self._error(self.socket, exc.code, f"la tarea {task_id} no existe")

    async def cancel_task(self, task_id: str) -> None:
        session = self.runtime.session
        if session is not None and task_id in session.active_task_ids:
            await session.cancel_active()
            return
        await self.runtime.orchestrator.cancel(task_id)

    async def set_mode(self, reply_mode: str) -> None:
        try:
            self.runtime.memory.settings.set_reply_mode(reply_mode)
        except ValueError as exc:
            if self.socket is not None:
                await self._error(self.socket, "invalid_reply_mode", str(exc))

    def reply_mode(self) -> str:
        persisted = self.runtime.memory.settings.load().reply_mode
        return persisted or self.runtime.settings.reply_mode

    async def aclose(self) -> None:
        socket = self.socket
        if socket is not None:
            self.detach(socket)
            with contextlib.suppress(Exception):
                await socket.close(CLOSE_GOING_AWAY)
        session = self.runtime.session
        if session is not None:
            await session.cancel_active()
        if self.turn is not None:
            await asyncio.gather(self.turn, return_exceptions=True)
        await self._close_conversation()

    async def _open_conversation(self, requested: str | None) -> None:
        runtime = self.runtime
        assert self.router is not None and self.usage is not None and self.gate is not None
        conversation_id = requested or runtime.memory.conversations.start_conversation(WEB_CHANNEL)
        self.stream = ConversationStream(conversation_id)
        self.gate.stream = self.stream
        self.channel = WebChannel(
            self.stream,
            self.router,
            runtime.orchestrator,
            self.usage,
            runtime.options.logs_dir,
            runtime.settings.limits.confirm_timeout_s,
        )
        self.conversation_id = conversation_id
        await runtime.open_session(conversation_id, self.channel)

    async def _close_conversation(self) -> None:
        channel, self.channel = self.channel, None
        self.conversation_id = None
        self.stream = None
        try:
            await self.runtime.close_session()
        finally:
            if channel is not None:
                await channel.close()

    async def _attach(self, socket: SocketLike, last_seq: int) -> None:
        assert self.stream is not None
        replay = self.stream.replay(last_seq)
        await socket.send_text(self._hello_ok(replay is None).to_json())
        queue = OutboundQueue()
        queue.prefill(replay or [])
        self.socket = socket
        self.stream.attach(queue)
        self._emitter = asyncio.create_task(self._pump(socket, queue))

    def _hello_ok(self, resync: bool) -> Envelope:
        assert self.stream is not None and self.router is not None
        payload: dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "reply_mode": self.reply_mode(),
            "last_seq": self.stream.last_seq,
            "state": self._state_payload(),
        }
        if resync:
            payload["resync"] = True
        return Envelope(type=HELLO_OK, seq=0, conversation_id=self.conversation_id, payload=payload)

    def _state_payload(self) -> dict[str, Any]:
        assert self.router is not None
        session = self.runtime.session
        active = session.active_task_ids if session is not None else set()
        tasks = self.runtime.orchestrator.tasks
        pending = self.router.pending()
        return {
            "turn_in_progress": self.turn_in_progress,
            "active_tasks": [
                {"task_id": task.id, "parent_id": task.parent_id, "status": task.status.value}
                for task in tasks.values()
                if task.id in active
            ],
            "pending_confirmation": None
            if pending is None
            else {
                "confirmation_id": pending.confirmation_id,
                "task_id": pending.task_id,
                "tool": pending.tool,
                "args": pending.args,
                "expires_in_s": pending.expires_in_s,
            },
        }

    async def _run_turn(self, text: str) -> None:
        session, channel = self.runtime.session, self.channel
        assert session is not None and channel is not None
        try:
            await session.handle(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the socket must learn that the turn died
            detail = f"{exc.__class__.__name__}: {exc}"
            await channel.send(
                AssistantReply(TURN_CRASHED.format(error=detail), None, "text", error=detail)
            )

    async def _pump(self, socket: SocketLike, queue: OutboundQueue) -> None:
        try:
            while True:
                envelope = await queue.get()
                await socket.send_text(envelope.to_json())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a dead socket just detaches; the turn goes on
            self.detach(socket)

    async def _error(self, socket: SocketLike, code: str, detail: str) -> None:
        with contextlib.suppress(Exception):
            await socket.send_text(error_envelope(code, detail, self.conversation_id).to_json())
