"""Application service of the front: one user message in, one assistant reply out."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from tony.core.channels.ports import (
    AssistantDelta,
    AssistantReply,
    AssistantSpeechDelta,
    AssistantWait,
    Channel,
    DelegationStarted,
    NeedsConfirmation,
    Notice,
    TaskEvent,
    TaskProgress,
    UserAccepted,
)
from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.logging import redact, utc_timestamp
from tony.core.mcp import ToolCatalog
from tony.core.memory.conversations import ConversationStore
from tony.core.memory.preferences import PreferencesStore
from tony.core.memory.settings import SettingsStore
from tony.core.orchestrator.clock import Clock, SystemClock
from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.orchestrator import Orchestrator
from tony.core.orchestrator.task import (
    SUBTASK_FINISHED,
    SUBTASK_STARTED,
    TASK_CANCELLED,
    TASK_FINISHED,
    TASK_NEEDS_CONFIRMATION,
    TASK_PROGRESS,
    TASK_RESULT,
    Event,
)
from tony.core.runner import EventSink, TaskRequest, TaskResult
from tony.core.runner.cancel import USER_REASON
from tony.core.runner.claude_sdk import SKILL_ACTIVATED
from tony.core.runner.conversation import ConversationRunner
from tony.core.runner.front_prompt import PREAMBLE_END, PREAMBLE_START, build_turn_preamble
from tony.core.runner.reply_mode import (
    PREFIX_FOR_MODE,
    EffectiveMode,
    InputModality,
    parse_front_reply,
    resolve_reply_mode,
    strip_prefix,
)
from tony.core.skills.index import find_skill
from tony.core.skills.triggers import matched_skills, skill_blocks

WAIT_PHRASE_DELAY_S = 3.0
FRONT_INTERRUPTED_REASON = "front_interrupted"
SESSION_STARTED = "session.started"
MISSING_TEXT_NOTICE = "Falta el mensaje después del prefijo {prefix}."
RESUME_FAILED_NOTICE = "No se pudo reanudar la sesión anterior del front; se empieza de cero."
TAGGED_PREFERENCE = "La preferencia no puede contener etiquetas de contexto."
REPLY_MODE_LOCKED = "El modo de respuesta está fijado en voz por el usuario y no se puede cambiar."
INTERRUPTED_SUFFIX = " …"
INTERRUPTED_PLACEHOLDER = "(interrumpido)"
CHANNEL_NAME = "cli"
CONFIG_TASK_ID = "config"


@dataclass
class Memory:
    preferences: PreferencesStore
    settings: SettingsStore
    conversations: ConversationStore


class _NullSink:
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


def local_now() -> datetime:
    return datetime.now().astimezone()


class ChatSession:
    def __init__(
        self,
        front: AgentSpec,
        runner: ConversationRunner,
        orchestrator: Orchestrator,
        channel: Channel,
        memory: Memory,
        settings: TonySettings,
        clock: Clock | None = None,
        now: Callable[[], datetime] = local_now,
        events: EventSink | None = None,
        catalog: ToolCatalog | None = None,
        secrets: list[str] | None = None,
    ) -> None:
        self._front = front
        self._runner = runner
        self._orchestrator = orchestrator
        self._channel = channel
        self._memory = memory
        self._settings = settings
        self._clock = clock or SystemClock()
        self._now = now
        self._events = events or _NullSink()
        self._catalog = catalog or ToolCatalog.empty()
        self._secrets = list(secrets or [])
        self.conversation_id: str | None = None
        self.active_task_ids: set[str] = set()
        self._supervisors: set[asyncio.Task[None]] = set()
        self._closed = False
        self._turn: _TurnInFlight | None = None

    @property
    def has_active_task(self) -> bool:
        return bool(self.active_task_ids)

    @property
    def turn_in_progress(self) -> bool:
        return self._turn is not None

    async def start(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._events.emit(
            SESSION_STARTED, {"conversation_id": conversation_id, "front": self._front.name}
        )
        resume = self._memory.conversations.sdk_session(conversation_id)
        try:
            await self._runner.open(self._front, self._catalog, self, self._events, resume=resume)
        except Exception:
            if resume is None:
                raise
            await self._channel.send(Notice(RESUME_FAILED_NOTICE))
            await self._runner.open(self._front, self._catalog, self, self._events)

    async def handle(
        self, text: str, modality: InputModality = "text", message_id: str | None = None
    ) -> AssistantReply | None:
        accepted = await self._accept(text, modality, message_id)
        if accepted is None:
            return None
        mode, message = accepted
        reply_id = uuid.uuid4().hex
        in_flight = self._turn = _TurnInFlight(reply_id, mode.mode)
        try:
            turn = await self._runner.turn(
                self._prompt_for(message, mode, modality),
                on_text=self._delta_sender(in_flight),
                on_speech=self._speech_sender(reply_id) if mode.mode != "text" else None,
            )
        finally:
            self._turn = None
        self._persist_sdk_session()
        if in_flight.interrupted:
            reply = AssistantReply(
                in_flight.interrupted_text(),
                None,
                mode.mode,
                message_id=reply_id,
                usage=dict(turn.usage),
                interrupted=True,
            )
        else:
            front_reply = parse_front_reply(turn.structured, turn.text, mode.mode)
            reply = AssistantReply(
                front_reply.display_text,
                front_reply.speech_text,
                mode.mode,
                message_id=reply_id,
                usage=dict(turn.usage),
                error=turn.error,
            )
        self._store_message("assistant", reply.display_text, mode.mode, reply_id)
        await self._channel.send(reply)
        return reply

    async def _accept(
        self, text: str, modality: InputModality, message_id: str | None = None
    ) -> tuple[EffectiveMode, str] | None:
        prefix, message = strip_prefix(text)
        if prefix is not None and not message:
            notice = MISSING_TEXT_NOTICE.format(prefix=PREFIX_FOR_MODE[prefix])
            await self._channel.send(Notice(notice))
            return None
        mode = resolve_reply_mode(
            prefix, self._memory.settings.load().reply_mode, self._settings.reply_mode, modality
        )
        user_id = self._store_message("user", message, None, message_id)
        await self._channel.send(UserAccepted(user_id, mode.mode))
        return mode, message

    def _prompt_for(self, message: str, mode: EffectiveMode, modality: InputModality) -> str:
        preamble = build_turn_preamble(
            self._now(),
            mode,
            self._front.style,
            self._memory.preferences.injection_block(),
            input_modality=modality,
        )
        for skill in matched_skills(message, self._front.skills):
            self._events.emit(SKILL_ACTIVATED, {"skill": skill.name})
        return preamble + skill_blocks(message, self._front.skills) + message

    def _delta_sender(self, in_flight: _TurnInFlight) -> Callable[[str], Awaitable[None]]:
        async def on_text(text: str) -> None:
            in_flight.display.append(text)
            await self._channel.send(AssistantDelta(in_flight.reply_id, text))

        return on_text

    def _speech_sender(self, reply_id: str) -> Callable[[str], Awaitable[None]]:
        async def on_speech(text: str) -> None:
            await self._channel.send(AssistantSpeechDelta(reply_id, text))

        return on_speech

    async def cancel_active(self) -> None:
        if self.active_task_ids:
            await self.interrupt()

    async def interrupt(self) -> None:
        """Stop the current turn: cancel its delegated tasks, then interrupt the front runner."""
        for task_id in list(self.active_task_ids):
            await self._orchestrator.cancel(task_id, USER_REASON)
        await self._runner.interrupt()

    async def interrupt_turn(self) -> None:
        """Stop the front mid-generation without touching its delegated tasks.

        The turn then ends with what was already displayed; the error result the engine may
        report for the interruption is not a failure of the turn.
        """
        if self._turn is None:
            return
        self._turn.interrupted = True
        await self._runner.interrupt()

    async def close(self, close_orchestrator: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._runner.close()
        finally:
            if close_orchestrator:
                await self._orchestrator.close()
            await asyncio.gather(*self._supervisors, return_exceptions=True)

    async def delegate(self, request: TaskRequest) -> TaskResult:
        try:
            task = self._orchestrator.submit(request)
        except OrchestratorError as exc:
            return TaskResult(
                status="error",
                resumen=f"No se pudo encolar la tarea: {exc.code}",
                errores=[exc.code],
            )
        self.active_task_ids.add(task.id)
        if self._turn is not None:
            await self._channel.send(DelegationStarted(self._turn.reply_id, self._turn.mode))
        usage: dict[str, Any] = {}
        self._record_task(task.id, request, None, usage)
        forwarder = asyncio.ensure_future(self._forward_events(task.id, usage))
        waiter = asyncio.ensure_future(self._wait_phrase_once())
        try:
            result = await self._orchestrator.wait(task.id)
        except asyncio.CancelledError:
            self._supervise(self._settle_interrupted(task.id, request, usage, forwarder))
            raise
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            self.active_task_ids.discard(task.id)
        await asyncio.gather(forwarder, return_exceptions=True)
        result = self._redacted(result)
        self._record_task(task.id, request, result, usage)
        return result

    async def remember(self, text: str) -> str:
        if PREAMBLE_START in text or PREAMBLE_END in text:
            raise ValueError(TAGGED_PREFERENCE)
        line = self._memory.preferences.append(text, today=self._now().date())
        return f"Guardado: {line}"

    async def set_reply_mode(self, mode: str) -> str:
        if mode != "voice":
            raise ValueError(REPLY_MODE_LOCKED)
        self._memory.settings.set_reply_mode(mode)
        return mode

    async def read_skill(self, name: str) -> str:
        return find_skill(self._front.skills, name).body

    async def notify_reload(
        self, text: str, event_type: str | None = None, payload: dict[str, Any] | None = None
    ) -> None:
        await self._channel.send(Notice(text))
        if event_type is not None:
            await self._channel.send(
                TaskEvent(CONFIG_TASK_ID, None, event_type, dict(payload or {}), 0, utc_timestamp())
            )

    async def _settle_interrupted(
        self, task_id: str, request: TaskRequest, usage: dict[str, Any], forwarder: asyncio.Task
    ) -> None:
        await self._orchestrator.cancel(task_id, FRONT_INTERRUPTED_REASON)
        result = await self._orchestrator.wait(task_id)
        await asyncio.gather(forwarder, return_exceptions=True)
        self._record_task(task_id, request, self._redacted(result), usage)

    def _supervise(self, coroutine: Any) -> None:
        supervisor = asyncio.create_task(coroutine)
        self._supervisors.add(supervisor)
        supervisor.add_done_callback(self._supervisors.discard)

    async def _forward_events(self, task_id: str, usage: dict[str, Any]) -> None:
        asking = _PendingAsk()
        try:
            async for event in self._orchestrator.events(task_id):
                await self._channel.send(self._task_event(event))
                payload = event.payload
                if event.type == TASK_PROGRESS:
                    await self._channel.send(
                        TaskProgress(task_id, payload["tool"], payload["step"])
                    )
                elif event.type == TASK_NEEDS_CONFIRMATION:
                    owner = payload.get("task_id", task_id)
                    asking.replace(owner, self._channel.send(_needs_confirmation(owner, payload)))
                elif event.type == TASK_FINISHED:
                    usage.update(payload.get("usage") or {})
                elif event.type == SUBTASK_STARTED:
                    self.active_task_ids.add(payload["task_id"])
                elif event.type == SUBTASK_FINISHED:
                    self.active_task_ids.discard(payload["task_id"])
                    asking.cancel_if(payload["task_id"])
                elif event.type in (TASK_CANCELLED, TASK_RESULT):
                    asking.cancel_if(task_id)
        finally:
            await asking.close()

    async def _wait_phrase_once(self) -> None:
        await self._clock.sleep(WAIT_PHRASE_DELAY_S)
        await self._channel.send(AssistantWait(self._front.wait_phrase))

    def _task_event(self, event: Event) -> TaskEvent:
        return TaskEvent(
            event.task_id,
            event.parent_id,
            event.type,
            redact(event.payload, self._secrets),
            event.seq,
            event.ts,
        )

    def _redacted[M: BaseModel](self, model: M) -> M:
        return model.model_validate(redact(model.model_dump(), self._secrets))

    def _persist_sdk_session(self) -> None:
        session_id = self._runner.session_id
        assert self.conversation_id is not None
        if session_id and session_id != self._memory.conversations.sdk_session(
            self.conversation_id
        ):
            self._memory.conversations.set_sdk_session(self.conversation_id, session_id)

    def _store_message(
        self, role: str, content: str, reply_mode: str | None, message_id: str | None = None
    ) -> str:
        assert self.conversation_id is not None, "start() must run before handle()"
        return self._memory.conversations.add_message(
            self.conversation_id, role, redact(content, self._secrets), reply_mode, message_id
        )

    def _record_task(
        self, task_id: str, request: TaskRequest, result: TaskResult | None, usage: dict[str, Any]
    ) -> None:
        assert self.conversation_id is not None
        task = self._orchestrator.tasks[task_id]
        self._memory.conversations.record_task(
            task_id,
            self.conversation_id,
            status=task.status.value,
            request=self._redacted(request),
            result=result,
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
            cost_usd=float(usage.get("total_cost_usd", 0.0) or 0.0),
        )


@dataclass
class _TurnInFlight:
    reply_id: str
    mode: str
    display: list[str] = field(default_factory=list)
    interrupted: bool = False

    def interrupted_text(self) -> str:
        said = "".join(self.display).rstrip()
        return said + INTERRUPTED_SUFFIX if said else INTERRUPTED_PLACEHOLDER


def _needs_confirmation(task_id: str, payload: dict[str, Any]) -> NeedsConfirmation:
    return NeedsConfirmation(task_id, payload["confirmation_id"], payload["tool"], payload["args"])


class _PendingAsk:
    """The confirmation prompt in flight; withdrawn when its task ends."""

    def __init__(self) -> None:
        self._task_id: str | None = None
        self._sending: asyncio.Task[None] | None = None

    def replace(self, task_id: str, sending: Any) -> None:
        self._withdraw()
        self._task_id = task_id
        self._sending = asyncio.ensure_future(sending)

    def cancel_if(self, task_id: str) -> None:
        if self._task_id == task_id:
            self._withdraw()

    async def close(self) -> None:
        sending = self._sending
        self._withdraw()
        if sending is not None:
            await asyncio.gather(sending, return_exceptions=True)

    def _withdraw(self) -> None:
        if self._sending is not None:
            self._sending.cancel()
        self._sending = None
        self._task_id = None
