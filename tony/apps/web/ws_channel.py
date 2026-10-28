"""Channel adapter of the web: every ChannelMessage becomes a numbered envelope on the stream."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from tony.apps.web.confirmations import ConfirmationRouter
from tony.apps.web.protocol import (
    ASSISTANT_DELTA,
    ASSISTANT_FINAL,
    ASSISTANT_WAIT,
    ERROR,
    USAGE,
    USER_ACCEPTED,
    ConversationStream,
)
from tony.core.channels.ports import (
    AssistantDelta,
    AssistantReply,
    AssistantWait,
    ChannelMessage,
    NeedsConfirmation,
    Notice,
    TaskEvent,
    UserAccepted,
)
from tony.core.channels.session import CONFIG_TASK_ID
from tony.core.orchestrator.clock import Clock, SystemClock
from tony.core.orchestrator.task import (
    SUBTASK_STARTED,
    TASK_CANCELLED,
    TASK_CONFIRMED,
    TASK_FINISHED,
    TASK_NEEDS_CONFIRMATION,
    TASK_QUEUED,
    TASK_RESULT,
    Event,
)

TURN_FAILED = "turn_failed"
NOTICE = "notice"
DRAIN_TIMEOUT_S = 5.0
Handler = Callable[[TaskEvent, dict[str, Any]], Awaitable[None]]


class TaskSource(Protocol):
    async def confirm(
        self,
        confirmation_id: str,
        approved: bool,
        tool: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> None: ...

    def events(self, task_id: str) -> Any: ...


class UsageTracker:
    """Tokens per root task (root plus every subtask) and the alert threshold."""

    def __init__(self, token_alert: int) -> None:
        self._token_alert = token_alert
        self._cumulative: dict[str, int] = {}

    def record(self, task_id: str, root_id: str, usage: dict[str, Any]) -> dict[str, Any]:
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        total = self._cumulative.get(root_id, 0) + input_tokens + output_tokens
        self._cumulative[root_id] = total
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": float(usage.get("total_cost_usd", 0.0) or 0.0),
            "cumulative_tokens": total,
            "alert": total > self._token_alert,
        }


class TaskStreamer:
    """Forwards task events, follows subtasks and turns `task.finished` into `usage`."""

    def __init__(
        self,
        stream: ConversationStream,
        router: ConfirmationRouter,
        source: TaskSource,
        usage: UsageTracker,
        logs_dir: Path,
        clock: Clock | None = None,
    ) -> None:
        self._stream = stream
        self._router = router
        self._source = source
        self._usage = usage
        self._logs_dir = logs_dir
        self._clock = clock or SystemClock()
        self._roots: dict[str, str] = {}
        self._subscriptions: dict[str, asyncio.Task[None]] = {}
        self._before: dict[str, Handler] = {
            TASK_QUEUED: self._on_queued,
            SUBTASK_STARTED: self._on_subtask_started,
        }
        self._after: dict[str, Handler] = {
            TASK_FINISHED: self._on_finished,
            TASK_CONFIRMED: self._on_ended,
            TASK_CANCELLED: self._on_ended,
            TASK_RESULT: self._on_result,
        }

    @property
    def active_subscriptions(self) -> int:
        return sum(1 for task in self._subscriptions.values() if not task.done())

    async def forward(self, event: TaskEvent) -> None:
        if event.task_id == CONFIG_TASK_ID:
            await self._stream.publish(event.type, dict(event.payload))
            return
        if event.type == TASK_NEEDS_CONFIRMATION:
            return
        payload = dict(event.payload)
        if event.parent_id is not None:
            payload["parent_id"] = event.parent_id
        before = self._before.get(event.type)
        if before is not None:
            await before(event, payload)
        await self._stream.publish(event.type, payload, task_id=event.task_id)
        after = self._after.get(event.type)
        if after is not None:
            await after(event, payload)

    async def close(self) -> None:
        subscriptions, self._subscriptions = list(self._subscriptions.values()), {}
        for task in subscriptions:
            task.cancel()
        await asyncio.gather(*subscriptions, return_exceptions=True)

    async def _on_queued(self, event: TaskEvent, payload: dict[str, Any]) -> None:
        self._roots.setdefault(event.task_id, event.parent_id or event.task_id)
        found = next(iter(self._logs_dir.glob(f"*/{event.task_id}.jsonl")), None)
        payload["log_path"] = str(found) if found is not None else None

    async def _on_subtask_started(self, event: TaskEvent, payload: dict[str, Any]) -> None:
        child_id = payload["task_id"]
        self._roots[child_id] = self._roots.get(event.task_id, event.task_id)
        if child_id not in self._subscriptions:
            self._subscriptions[child_id] = asyncio.create_task(self._follow(child_id))

    async def _on_finished(self, event: TaskEvent, payload: dict[str, Any]) -> None:
        root_id = self._roots.get(event.task_id, event.parent_id or event.task_id)
        usage = self._usage.record(event.task_id, root_id, payload.get("usage") or {})
        await self._stream.publish(USAGE, usage, task_id=event.task_id)

    async def _on_ended(self, event: TaskEvent, payload: dict[str, Any]) -> None:
        self._router.discard_task(event.task_id)

    async def _on_result(self, event: TaskEvent, payload: dict[str, Any]) -> None:
        self._router.discard_task(event.task_id)
        if self._roots.get(event.task_id, event.task_id) == event.task_id:
            await self._drain_children_of(event.task_id)

    async def _drain_children_of(self, root_id: str) -> None:
        """Let the children's consumers forward their remaining history, up to DRAIN_TIMEOUT_S."""
        children = [c for c, root in self._roots.items() if root == root_id and c != root_id]
        tasks = [self._subscriptions[c] for c in children if c in self._subscriptions]
        if not tasks:
            return
        drained = asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True))
        budget = asyncio.ensure_future(self._clock.sleep(DRAIN_TIMEOUT_S))
        await asyncio.wait({drained, budget}, return_when=asyncio.FIRST_COMPLETED)
        budget.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(drained, budget, return_exceptions=True)
        for child in children:
            self._subscriptions.pop(child, None)

    async def _follow(self, child_id: str) -> None:
        async for event in self._source.events(child_id):
            await self.forward(_as_channel_event(event))


def _as_channel_event(event: Event) -> TaskEvent:
    return TaskEvent(event.task_id, event.parent_id, event.type, event.payload, event.seq, event.ts)


class WebChannel:
    def __init__(
        self,
        stream: ConversationStream,
        router: ConfirmationRouter,
        source: TaskSource,
        usage: UsageTracker,
        logs_dir: Path,
        confirm_timeout_s: float,
        clock: Clock | None = None,
    ) -> None:
        self._stream = stream
        self._router = router
        self._source = source
        self._usage = usage
        self._confirm_timeout_s = confirm_timeout_s
        self.client_id: str | None = None
        self.streamer = TaskStreamer(stream, router, source, usage, logs_dir, clock)

    async def send(self, message: ChannelMessage) -> None:
        if isinstance(message, UserAccepted):
            await self._send_accepted(message)
        elif isinstance(message, AssistantDelta):
            await self._stream.publish(
                ASSISTANT_DELTA, {"text": message.text}, message_id=message.message_id
            )
        elif isinstance(message, AssistantWait):
            await self._stream.publish(ASSISTANT_WAIT, {"text": message.text})
        elif isinstance(message, AssistantReply):
            await self._send_reply(message)
        elif isinstance(message, Notice):
            await self._stream.publish(ERROR, {"code": NOTICE, "detail": message.text})
        elif isinstance(message, NeedsConfirmation):
            await self._ask(message)
        elif isinstance(message, TaskEvent):
            await self.streamer.forward(message)

    async def close(self) -> None:
        await self.streamer.close()

    async def _send_accepted(self, accepted: UserAccepted) -> None:
        client_id, self.client_id = self.client_id, None
        payload = {
            "message_id": accepted.message_id,
            "effective_mode": accepted.effective_mode,
            "client_id": client_id,
        }
        await self._stream.publish(USER_ACCEPTED, payload, message_id=accepted.message_id)

    async def _send_reply(self, reply: AssistantReply) -> None:
        if reply.error is not None:
            await self._stream.publish(ERROR, {"code": TURN_FAILED, "detail": reply.error})
        turn_id = f"front:{reply.message_id}"
        usage = {"task_id": None, **self._usage.record(turn_id, turn_id, reply.usage)}
        await self._stream.publish(USAGE, usage)
        await self._stream.publish(
            ASSISTANT_FINAL,
            {
                "display_text": reply.display_text,
                "speech_text": reply.speech_text,
                "message_id": reply.message_id,
            },
            message_id=reply.message_id,
        )

    async def _ask(self, request: NeedsConfirmation) -> None:
        async def resolver(approved: bool) -> None:
            await self._source.confirm(
                request.confirmation_id, approved, request.tool, request.args
            )

        self._router.register(
            request.confirmation_id, request.task_id, request.tool, request.args, resolver
        )
        await self._stream.publish(
            TASK_NEEDS_CONFIRMATION,
            {
                "confirmation_id": request.confirmation_id,
                "tool": request.tool,
                "args": request.args,
                "expires_in_s": self._confirm_timeout_s,
            },
            task_id=request.task_id,
        )
