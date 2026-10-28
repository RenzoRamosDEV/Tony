"""Per-task event bus (history + live subscribers) and the sink the worker writes to."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from tony.core.logging import utc_timestamp
from tony.core.orchestrator.task import TASK_PROGRESS, TASK_RESULT, TOOL_CALL, Event
from tony.core.runner.ports import EventSink

_END = None


class TaskEventBus:
    def __init__(self, task_id: str, now: Callable[[], str] = utc_timestamp) -> None:
        self._task_id = task_id
        self._now = now
        self.history: list[Event] = []
        self.closed = False
        self._subscribers: set[asyncio.Queue[Event | None]] = set()

    def publish(self, event_type: str, payload: dict[str, Any]) -> Event:
        event = Event(self._task_id, event_type, payload, len(self.history) + 1, self._now())
        self.history.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)
        if event_type == TASK_RESULT:
            self.closed = True
            for queue in self._subscribers:
                queue.put_nowait(_END)
        return event

    async def stream(self) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            for event in list(self.history):
                yield event
            if self.closed:
                return
            while (event := await queue.get()) is not _END:
                yield event
        finally:
            self._subscribers.discard(queue)


class TaskEventSink:
    """EventSink handed to the worker: every event goes to the log and the bus."""

    def __init__(self, bus: TaskEventBus, log: EventSink | None = None) -> None:
        self._bus = bus
        self._log = log
        self._steps = 0

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self._publish(event_type, payload)
        if event_type == TOOL_CALL:
            self._steps += 1
            self._publish(TASK_PROGRESS, {"tool": payload.get("tool"), "step": self._steps})

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._log is not None:
            self._log.emit(event_type, payload)
        self._bus.publish(event_type, payload)
