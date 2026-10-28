"""Generations of MCP servers: tasks lease the current one; a reload swaps in a new one and
the old generation is stopped once no task uses it any more."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from tony.core.config import TonySettings
from tony.core.loader import ToolConfig
from tony.core.mcp.owner import CLOSE_BUDGET_S, ManagerOwner
from tony.core.mcp.ports import ManagerFactory, ToolManager

POOL_CLOSED = "el pool de MCPs se cerró durante el arranque"
logger = logging.getLogger(__name__)


@dataclass
class Generation:
    id: int
    tool_config: ToolConfig
    owner: ManagerOwner
    manager: ToolManager
    leases: int = 0
    retired: bool = False


class McpGenerationPool:
    def __init__(
        self,
        manager_factory: ManagerFactory,
        settings: TonySettings,
        tool_config: ToolConfig,
        close_budget_s: float = CLOSE_BUDGET_S,
    ) -> None:
        self._manager_factory = manager_factory
        self._settings = settings
        self._tool_config = tool_config
        self._close_budget_s = close_budget_s
        self._current: Generation | None = None
        self._retired: list[Generation] = []
        self._pending: list[ManagerOwner] = []
        self._next_id = 1
        self._initial_start = asyncio.Lock()

    @property
    def current(self) -> Generation | None:
        return self._current

    async def acquire(self) -> Generation:
        async with self._initial_start:
            generation = self._current or await self._start_initial()
            generation.leases += 1
            return generation

    def lease(self, generation: Generation) -> None:
        generation.leases += 1

    async def release(self, generation: Generation) -> None:
        generation.leases = max(0, generation.leases - 1)
        if generation.retired and generation.leases == 0:
            await self._stop(generation)

    async def swap(
        self, tool_config: ToolConfig, on_publish: Callable[[], None] | None = None
    ) -> Generation:
        """Start the new generation and only then publish it, together with `on_publish`."""
        new = await self._start(tool_config)
        old, self._current = self._current, new
        self._tool_config = tool_config
        if on_publish is not None:
            on_publish()
        if old is not None:
            old.retired = True
            if old.leases == 0:
                await self._stop(old)
            else:
                self._retired.append(old)
        return new

    async def close_all(self) -> None:
        generations = [*self._retired, *([self._current] if self._current else [])]
        self._retired.clear()
        self._current = None
        for generation in generations:
            await self._stop(generation)
        pending, self._pending = self._pending, []
        for owner in pending:
            await owner.stop()

    async def _start_initial(self) -> Generation:
        generation = await self._start(self._tool_config)
        published = self._current
        if published is None:
            self._current = generation
            return generation
        # A swap published while the first start was in flight: the late start loses.
        await self._stop(generation)
        return published

    async def _start(self, tool_config: ToolConfig) -> Generation:
        owner = ManagerOwner(
            self._manager_factory(self._settings), tool_config, self._close_budget_s
        )
        self._pending.append(owner)
        manager = await owner.manager()
        if owner not in self._pending:
            raise RuntimeError(POOL_CLOSED)
        self._pending.remove(owner)
        generation = Generation(self._next_id, tool_config, owner, manager)
        self._next_id += 1
        return generation

    async def _stop(self, generation: Generation) -> None:
        if generation in self._retired:
            self._retired.remove(generation)
        try:
            await generation.owner.stop()
        except Exception as exc:  # noqa: BLE001 - closing a generation never raises
            logger.warning("error al cerrar la generación %s de MCPs: %s", generation.id, exc)
