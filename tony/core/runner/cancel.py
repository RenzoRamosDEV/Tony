"""Cooperative cancellation shared by the orchestrator, the runner and the proxies."""

from __future__ import annotations

import asyncio

USER_REASON = "user"
NOT_CONFIRMED_REASON = "not_confirmed"


class CancelToken:
    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.reason: str | None = None

    @property
    def cancelled(self) -> bool:
        return self.event.is_set()

    def cancel(self, reason: str) -> None:
        if not self.cancelled:
            self.reason = reason
            self.event.set()

    async def wait(self) -> None:
        await self.event.wait()


def cancellation_error(reason: str | None) -> str:
    if reason == USER_REASON:
        return "cancelada por el usuario"
    return f"cancelada: {reason or 'desconocido'}"
