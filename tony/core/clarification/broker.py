import asyncio

from tony.core.clarification.request import ClarificationRequest
from tony.core.events import core_events
from tony.core.events.core_events import Publisher
from tony.core.logging.task_log import Clock, utc_now


class ClarificationBroker:
    """Desktop question channel: publishes one question at a time and awaits its answer.

    Kept apart from the confirmation broker: an answer here never approves anything.
    """

    def __init__(self, publish: Publisher, *, clock: Clock = utc_now) -> None:
        self._publish = publish
        self._clock = clock
        self._lock = asyncio.Lock()
        self._pending: tuple[ClarificationRequest, asyncio.Future[str | None]] | None = None

    async def ask(self, request: ClarificationRequest) -> str | None:
        async with self._lock:
            answer: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            self._pending = (request, answer)
            self._publish(
                core_events.clarification_requested(
                    request.request_id,
                    request.task_id,
                    request.agent,
                    request.question,
                    request.options,
                    clock=self._clock,
                )
            )
            try:
                return await answer
            finally:
                self._pending = None

    def answer(self, request_id: str, answer: str) -> None:
        """Resolve the pending question; an answer that does not match it is ignored."""
        if self._pending is None:
            return
        request, future = self._pending
        if request.request_id == request_id and not future.done():
            future.set_result(answer)

    def cancel(self) -> None:
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_result(None)
