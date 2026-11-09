import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from tony.core.events import core_events
from tony.core.events.core_events import Publisher
from tony.core.guard.allow_always import insert_allow_always
from tony.core.guard.confirm import ConfirmationRequest
from tony.core.guard.policy import policy_file
from tony.core.logging.task_log import utc_now

ConfirmDecision = Literal["allow", "deny", "always"]
YES_DECISIONS = ("allow", "always")


class ConfirmationBroker:
    """Desktop confirmation channel: publishes one request at a time and awaits its answer."""

    def __init__(
        self,
        root: Path,
        guard: str,
        publish: Publisher,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._root = root
        self._clock = clock
        self._guard = guard
        self._publish = publish
        self._lock = asyncio.Lock()
        self._pending: tuple[ConfirmationRequest, asyncio.Future[bool]] | None = None
        self.always_allowed: set[str] = set()

    async def ask(self, request: ConfirmationRequest) -> bool | None:
        async with self._lock:
            if request.tool in self.always_allowed:
                return True
            answer: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._pending = (request, answer)
            self._publish(
                core_events.needs_confirmation(
                    request.task_id,
                    request.tool,
                    request.args_preview,
                    request.question,
                    request.allow_always,
                    approval_id=request.approval_id,
                    args_digest=request.args_digest,
                    policy_version=request.policy_version,
                    expires_at=request.expires_at,
                    preview=request.preview,
                )
            )
            try:
                return await answer
            finally:
                self._pending = None

    def answer(
        self, task_id: str, decision: ConfirmDecision, approval_id: str | None = None
    ) -> None:
        """Resolve the pending approval; an answer that does not match it is ignored."""
        if self._pending is None:
            return
        request, answer = self._pending
        if answer.done() or not self._matches(request, task_id, approval_id):
            return
        if decision == "always" and request.allow_always:
            self._allow_always(request.tool)
        answer.set_result(decision in YES_DECISIONS)

    def _matches(self, request: ConfirmationRequest, task_id: str, approval_id: str | None) -> bool:
        if request.task_id != task_id:
            return False
        if approval_id is not None and approval_id != request.approval_id:
            return False
        return request.expires_at is None or self._clock() < request.expires_at

    def cancel(self) -> None:
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_result(False)

    def _allow_always(self, tool: str) -> None:
        self.always_allowed.add(tool)
        try:
            insert_allow_always(self._root, self._guard, tool)
        except Exception as error:
            self._publish(
                core_events.error("edith", f"could not update {policy_file(self._guard)}: {error}")
            )
