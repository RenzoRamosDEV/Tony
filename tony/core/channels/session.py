"""Application service of the front: one user message in, one assistant reply out."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tony.core.channels.ports import (
    AssistantReply,
    AssistantWait,
    Channel,
    NeedsConfirmation,
    Notice,
    TaskProgress,
)
from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.memory.conversations import ConversationStore
from tony.core.memory.preferences import PreferencesStore
from tony.core.memory.settings import SettingsStore
from tony.core.orchestrator.clock import Clock, SystemClock
from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.orchestrator import Orchestrator
from tony.core.orchestrator.task import TASK_FINISHED, TASK_NEEDS_CONFIRMATION, TASK_PROGRESS
from tony.core.runner import EventSink, TaskRequest, TaskResult
from tony.core.runner.cancel import USER_REASON
from tony.core.runner.conversation import ConversationRunner
from tony.core.runner.front_prompt import build_turn_preamble
from tony.core.runner.reply_mode import (
    PREFIX_FOR_MODE,
    InputModality,
    parse_front_reply,
    resolve_reply_mode,
    strip_prefix,
)

WAIT_PHRASE_DELAY_S = 3.0
SESSION_STARTED = "session.started"
MISSING_TEXT_NOTICE = "Falta el mensaje después del prefijo {prefix}."
CHANNEL_NAME = "cli"


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
        self.conversation_id: str | None = None
        self.active_task_id: str | None = None

    async def start(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._events.emit(
            SESSION_STARTED, {"conversation_id": conversation_id, "front": self._front.name}
        )
        await self._runner.open(self._front, self._catalog, self, self._events)

    async def handle(self, text: str, modality: InputModality = "text") -> AssistantReply | None:
        prefix, message = strip_prefix(text)
        if prefix is not None and not message:
            notice = MISSING_TEXT_NOTICE.format(prefix=PREFIX_FOR_MODE[prefix])
            await self._channel.send(Notice(notice))
            return None
        mode = resolve_reply_mode(
            prefix, self._memory.settings.load().reply_mode, self._settings.reply_mode, modality
        )
        self._store_message("user", message, None)
        preamble = build_turn_preamble(
            self._now(), mode, self._front.style, self._memory.preferences.injection_block()
        )
        turn = await self._runner.turn(preamble + message)
        front_reply = parse_front_reply(turn.structured, turn.text, mode.mode)
        reply = AssistantReply(front_reply.display_text, front_reply.speech_text, mode.mode)
        self._store_message("assistant", reply.display_text, mode.mode)
        await self._channel.send(reply)
        return reply

    async def cancel_active(self) -> None:
        if self.active_task_id is None:
            return
        await self._orchestrator.cancel(self.active_task_id, USER_REASON)
        await self._runner.interrupt()

    async def close(self) -> None:
        await self._runner.close()
        await self._orchestrator.close()

    async def delegate(self, request: TaskRequest) -> TaskResult:
        try:
            task = self._orchestrator.submit(request)
        except OrchestratorError as exc:
            return TaskResult(
                status="error",
                resumen=f"No se pudo encolar la tarea: {exc.code}",
                errores=[exc.code],
            )
        self.active_task_id = task.id
        usage: dict[str, Any] = {}
        forwarder = asyncio.ensure_future(self._forward_events(task.id, usage))
        waiter = asyncio.ensure_future(self._wait_phrase_once())
        try:
            result = await self._orchestrator.wait(task.id)
        except BaseException:
            forwarder.cancel()
            raise
        finally:
            waiter.cancel()
            await asyncio.gather(forwarder, waiter, return_exceptions=True)
            self.active_task_id = None
        self._record_task(task.id, request, result, usage)
        return result

    async def remember(self, text: str) -> str:
        line = self._memory.preferences.append(text, today=self._now().date())
        return f"Guardado: {line}"

    async def set_reply_mode(self, mode: str) -> str:
        self._memory.settings.set_reply_mode(mode)
        return mode

    async def _forward_events(self, task_id: str, usage: dict[str, Any]) -> None:
        async for event in self._orchestrator.events(task_id):
            if event.type == TASK_PROGRESS:
                await self._channel.send(
                    TaskProgress(task_id, event.payload["tool"], event.payload["step"])
                )
            elif event.type == TASK_NEEDS_CONFIRMATION:
                await self._channel.send(
                    NeedsConfirmation(
                        task_id,
                        event.payload["confirmation_id"],
                        event.payload["tool"],
                        event.payload["args"],
                    )
                )
            elif event.type == TASK_FINISHED:
                usage.update(event.payload.get("usage") or {})

    async def _wait_phrase_once(self) -> None:
        await self._clock.sleep(WAIT_PHRASE_DELAY_S)
        await self._channel.send(AssistantWait(self._front.wait_phrase))

    def _store_message(self, role: str, content: str, reply_mode: str | None) -> None:
        assert self.conversation_id is not None, "start() must run before handle()"
        self._memory.conversations.add_message(self.conversation_id, role, content, reply_mode)

    def _record_task(
        self, task_id: str, request: TaskRequest, result: TaskResult, usage: dict[str, Any]
    ) -> None:
        assert self.conversation_id is not None
        task = self._orchestrator.tasks[task_id]
        self._memory.conversations.record_task(
            task_id,
            self.conversation_id,
            status=task.status.value,
            request=request,
            result=result,
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
            cost_usd=float(usage.get("total_cost_usd", 0.0) or 0.0),
        )
