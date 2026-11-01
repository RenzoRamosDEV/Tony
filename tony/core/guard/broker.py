import asyncio
from pathlib import Path
from typing import Literal

from tony.core.events import core_events
from tony.core.events.core_events import Publisher
from tony.core.guard.allow_always import insert_allow_always
from tony.core.guard.confirm import ConfirmationRequest
from tony.core.guard.policy import policy_file

ConfirmDecision = Literal["allow", "deny", "always"]
YES_DECISIONS = ("allow", "always")


class ConfirmationBroker:
    """Desktop confirmation channel: publishes one request at a time and awaits its answer."""

    def __init__(self, root: Path, guard: str, publish: Publisher) -> None:
        self._root = root
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
                )
            )
            try:
                return await answer
            finally:
                self._pending = None

    def answer(self, task_id: str, decision: ConfirmDecision) -> None:
        if self._pending is None:
            return
        request, answer = self._pending
        if request.task_id != task_id or answer.done():
            return
        if decision == "always" and request.allow_always:
            self._allow_always(request.tool)
        answer.set_result(decision in YES_DECISIONS)

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
