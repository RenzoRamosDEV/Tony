"""Confirmations owned by the orchestrator: one pending per owner, single use, bound to args."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from tony.core.mcp import ConfirmRequest, normalize_args
from tony.core.orchestrator.errors import INVALID_CONFIRMATION, OrchestratorError


@dataclass
class PendingConfirmation:
    owner_id: str
    request: ConfirmRequest
    future: asyncio.Future[bool]
    invalidated: bool = False

    @property
    def confirmation_id(self) -> str:
        return self.request.confirmation_id

    def matches(self, tool: str | None, args: dict[str, Any] | None) -> bool:
        if tool is not None and tool != self.request.tool:
            return False
        return args is None or normalize_args(args) == self.request.args_normalized


class ConfirmationRegistry:
    def __init__(self) -> None:
        self._pending: dict[str, PendingConfirmation] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, owner_id: str) -> asyncio.Lock:
        return self._locks.setdefault(owner_id, asyncio.Lock())

    def register(self, owner_id: str, request: ConfirmRequest) -> PendingConfirmation:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        pending = PendingConfirmation(owner_id, request, future)
        self._pending[request.confirmation_id] = pending
        return pending

    def resolve(
        self,
        confirmation_id: str,
        approved: bool,
        tool: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> PendingConfirmation:
        pending = self._pending.get(confirmation_id)
        if pending is None or not pending.matches(tool, args):
            raise OrchestratorError(INVALID_CONFIRMATION)
        del self._pending[confirmation_id]
        pending.future.set_result(approved)
        return pending

    def discard(self, confirmation_id: str) -> None:
        self._pending.pop(confirmation_id, None)

    def invalidate_owner(self, owner_id: str) -> None:
        for confirmation_id, pending in list(self._pending.items()):
            if pending.owner_id == owner_id:
                del self._pending[confirmation_id]
                pending.invalidated = True
                if not pending.future.done():
                    pending.future.set_result(False)


class ConfirmationHost(Protocol):
    async def request_confirmation(self, task_id: str, request: ConfirmRequest) -> bool: ...


class OrchestratorConfirmGate:
    def __init__(self, host: ConfirmationHost, task_id: str) -> None:
        self._host = host
        self._task_id = task_id

    async def confirm(self, request: ConfirmRequest) -> bool:
        return await self._host.request_confirmation(self._task_id, request)
