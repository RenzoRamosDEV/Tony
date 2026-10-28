"""One router for every pending confirmation (orchestrator tasks and front tools)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from tony.apps.web.protocol import ConversationStream
from tony.core.mcp import ConfirmRequest
from tony.core.orchestrator.clock import Clock, SystemClock
from tony.core.orchestrator.errors import INVALID_CONFIRMATION, OrchestratorError
from tony.core.orchestrator.task import TASK_CANCELLED, TASK_CONFIRMED, TASK_NEEDS_CONFIRMATION
from tony.core.runner.cancel import NOT_CONFIRMED_REASON

FRONT_TASK_ID = "front"
Resolver = Callable[[bool], Awaitable[None]]


class InvalidConfirmation(Exception):
    code = INVALID_CONFIRMATION

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class PendingConfirmation:
    confirmation_id: str
    task_id: str
    tool: str
    args: dict[str, Any]
    deadline: float
    resolver: Resolver


@dataclass(frozen=True)
class PendingView:
    confirmation_id: str
    task_id: str
    tool: str
    args: dict[str, Any]
    expires_in_s: float


class ConfirmationRouter:
    def __init__(self, now: Callable[[], float], timeout_s: float) -> None:
        self._now = now
        self._timeout_s = timeout_s
        self._pending: dict[str, PendingConfirmation] = {}

    def register(
        self,
        confirmation_id: str,
        task_id: str,
        tool: str,
        args: dict[str, Any],
        resolver: Resolver,
    ) -> PendingConfirmation:
        pending = PendingConfirmation(
            confirmation_id, task_id, tool, args, self._now() + self._timeout_s, resolver
        )
        self._pending[confirmation_id] = pending
        return pending

    async def resolve(
        self, confirmation_id: str, approved: bool, task_id: str | None = None
    ) -> None:
        self._prune()
        pending = self._pending.get(confirmation_id)
        if pending is None:
            raise InvalidConfirmation(
                f"la confirmación {confirmation_id} no existe, caducó o ya se respondió"
            )
        if task_id is not None and task_id != pending.task_id:
            raise InvalidConfirmation(
                f"la confirmación {confirmation_id} pertenece a la tarea {pending.task_id}"
            )
        del self._pending[confirmation_id]
        try:
            await pending.resolver(approved)
        except OrchestratorError as exc:
            raise InvalidConfirmation(
                f"el orquestador rechazó la confirmación: {exc.code}"
            ) from None

    def pending(self) -> PendingView | None:
        self._prune()
        for pending in self._pending.values():
            return PendingView(
                pending.confirmation_id,
                pending.task_id,
                pending.tool,
                pending.args,
                max(0.0, pending.deadline - self._now()),
            )
        return None

    def discard(self, confirmation_id: str) -> None:
        self._pending.pop(confirmation_id, None)

    def discard_task(self, task_id: str) -> None:
        for confirmation_id in [c for c, p in self._pending.items() if p.task_id == task_id]:
            del self._pending[confirmation_id]

    def _prune(self) -> None:
        now = self._now()
        for confirmation_id in [c for c, p in self._pending.items() if p.deadline < now]:
            del self._pending[confirmation_id]


class WebConfirmGate:
    """ConfirmGate of the front: the question travels over the stream, the answer via the router."""

    def __init__(
        self,
        router: ConfirmationRouter,
        stream: ConversationStream | None,
        timeout_s: float,
        clock: Clock | None = None,
    ) -> None:
        self._router = router
        self.stream = stream
        self._timeout_s = timeout_s
        self._clock = clock or SystemClock()

    async def confirm(self, request: ConfirmRequest) -> bool:
        if self.stream is None:
            return False
        answer: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        async def resolver(approved: bool) -> None:
            if not answer.done():
                answer.set_result(approved)

        args = json.loads(request.args_normalized)
        self._router.register(request.confirmation_id, FRONT_TASK_ID, request.tool, args, resolver)
        await self.stream.publish(
            TASK_NEEDS_CONFIRMATION,
            {
                "confirmation_id": request.confirmation_id,
                "tool": request.tool,
                "args": args,
                "expires_in_s": self._timeout_s,
            },
            task_id=FRONT_TASK_ID,
        )
        approved = await self._await_answer(answer)
        if approved is None:
            self._router.discard(request.confirmation_id)
            await self.stream.publish(
                TASK_CANCELLED, {"reason": NOT_CONFIRMED_REASON}, task_id=FRONT_TASK_ID
            )
            return False
        await self.stream.publish(
            TASK_CONFIRMED,
            {"confirmation_id": request.confirmation_id, "approved": approved},
            task_id=FRONT_TASK_ID,
        )
        return approved

    async def _await_answer(self, answer: asyncio.Future[bool]) -> bool | None:
        expiry = asyncio.ensure_future(self._clock.sleep(self._timeout_s))
        try:
            done, _ = await asyncio.wait({answer, expiry}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            expiry.cancel()
            answer.cancel()
        return answer.result() if answer in done else None
