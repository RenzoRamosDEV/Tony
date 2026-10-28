"""ManagerOwner: a cancelled waiter must neither crash the owner nor leak the manager."""

from __future__ import annotations

import asyncio

import pytest

from tests.apps.cli_helpers import FakeManager
from tony.core.loader import StdioServer, ToolConfig
from tony.core.mcp.owner import ManagerOwner

TOOLS = ToolConfig(mcpServers={"fake": StdioServer(command="a")})


class BlockedManager(FakeManager):
    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__()
        self.gate = gate

    async def start(self, tool_config, server_filter=None) -> None:
        await self.gate.wait()
        await super().start(tool_config, server_filter)


async def test_cancelling_the_waiter_during_start_still_stops_the_manager() -> None:
    gate = asyncio.Event()
    manager = BlockedManager(gate)
    owner = ManagerOwner(manager, TOOLS)
    waiter = asyncio.ensure_future(owner.manager())
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    gate.set()

    await asyncio.wait_for(owner.stop(), 1)
    assert manager.started_with == TOOLS
    assert manager.stopped is True


async def test_owner_task_cancelled_after_start_still_stops_the_manager() -> None:
    manager = FakeManager()
    owner = ManagerOwner(manager, TOOLS)
    await owner.manager()

    owner._task.cancel()  # noqa: SLF001 - simulates loop teardown cancelling the owner
    with pytest.raises(asyncio.CancelledError):
        await owner._task  # noqa: SLF001

    assert manager.stopped is True


async def test_failed_start_is_raised_to_the_waiter_and_the_manager_is_stopped() -> None:
    class Broken(FakeManager):
        async def start(self, tool_config, server_filter=None) -> None:
            raise RuntimeError("npx missing")

    manager = Broken()
    owner = ManagerOwner(manager, TOOLS)

    with pytest.raises(RuntimeError, match="npx missing"):
        await owner.manager()
    await asyncio.wait_for(owner.stop(), 1)

    assert manager.stopped is True
