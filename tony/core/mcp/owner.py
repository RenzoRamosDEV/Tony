"""One long-lived task starts and stops a manager: MCP sessions bind their cancel scopes to
the task that opened them, so closing from another task raises inside anyio."""

from __future__ import annotations

import asyncio
import contextlib

from tony.core.loader import ToolConfig
from tony.core.mcp.ports import ToolManager

CLOSE_BUDGET_S = 5.0


class ManagerOwner:
    def __init__(
        self,
        manager: ToolManager,
        tools: ToolConfig,
        close_budget_s: float = CLOSE_BUDGET_S,
        server_filter: list[str] | None = None,
    ) -> None:
        self._close_budget_s = close_budget_s
        self._ready: asyncio.Future[ToolManager] = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._own(manager, tools, server_filter))

    async def manager(self) -> ToolManager:
        try:
            return await asyncio.shield(self._ready)
        except asyncio.CancelledError:
            # Nobody will use the manager once its only waiter is gone: stop it when started.
            self._stop.set()
            raise

    async def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._task, self._close_budget_s)

    async def _own(
        self, manager: ToolManager, tools: ToolConfig, server_filter: list[str] | None
    ) -> None:
        try:
            await manager.start(tools, server_filter)
        except BaseException as exc:
            self._publish(exc)
        else:
            self._publish(manager)
            await self._stop.wait()
        finally:
            await manager.stop()

    def _publish(self, outcome: ToolManager | BaseException) -> None:
        if self._ready.done():
            return
        if isinstance(outcome, BaseException):
            self._ready.set_exception(outcome)
        else:
            self._ready.set_result(outcome)
