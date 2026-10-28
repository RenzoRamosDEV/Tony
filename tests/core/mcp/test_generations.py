"""MCP generations: lease per task, swap on reload, retire when unused (specs/config-hot-reload)."""

from __future__ import annotations

import asyncio

import pytest

from tests.apps.cli_helpers import FakeManager
from tony.core.config import load_settings
from tony.core.loader import StdioServer, ToolConfig
from tony.core.mcp.generations import McpGenerationPool

SETTINGS = load_settings(None)
FIRST = ToolConfig(mcpServers={"fake": StdioServer(command="a")})
SECOND = ToolConfig(
    mcpServers={"fake": StdioServer(command="a"), "fake2": StdioServer(command="b")}
)


class Managers:
    def __init__(self, failing_stop: bool = False) -> None:
        self.created: list[FakeManager] = []
        self.failing_stop = failing_stop

    def factory(self, settings) -> FakeManager:
        manager = FakeManager()
        if self.failing_stop:

            async def stop() -> None:
                manager.stopped = True
                raise RuntimeError("no se pudo cerrar")

            manager.stop = stop  # type: ignore[method-assign]
        self.created.append(manager)
        return manager


def make_pool(managers: Managers | None = None) -> tuple[McpGenerationPool, Managers]:
    managers = managers or Managers()
    return McpGenerationPool(managers.factory, SETTINGS, FIRST), managers


async def test_first_acquire_starts_the_manager_and_leases_it() -> None:
    pool, managers = make_pool()
    assert pool.current is None and managers.created == []

    generation = await pool.acquire()

    assert pool.current is generation
    assert generation.leases == 1 and generation.retired is False
    assert generation.manager is managers.created[0]
    assert managers.created[0].started_with == FIRST
    assert generation.tool_config == FIRST
    assert (await pool.acquire()) is generation and generation.leases == 2


async def test_swap_without_leases_stops_the_old_generation_immediately() -> None:
    pool, managers = make_pool()
    old = await pool.acquire()
    await pool.release(old)

    new = await pool.swap(SECOND)

    assert pool.current is new and new is not old
    assert new.id == old.id + 1
    assert managers.created[1].started_with == SECOND
    assert old.retired is True and managers.created[0].stopped is True
    assert managers.created[1].stopped is False
    assert (await pool.acquire()) is new


async def test_swap_with_a_leased_task_keeps_the_old_generation_until_released() -> None:
    pool, managers = make_pool()
    old = await pool.acquire()

    new = await pool.swap(SECOND)
    assert old.retired is True and managers.created[0].stopped is False
    assert pool.current is new

    await pool.release(old)

    assert managers.created[0].stopped is True
    assert managers.created[1].stopped is False


async def test_release_of_the_current_generation_never_stops_it() -> None:
    pool, managers = make_pool()
    generation = await pool.acquire()

    await pool.release(generation)

    assert generation.leases == 0 and managers.created[0].stopped is False


async def test_swap_without_any_acquire_starts_the_new_generation_as_current() -> None:
    pool, managers = make_pool()

    new = await pool.swap(SECOND)

    assert pool.current is new and len(managers.created) == 1


async def test_failing_stop_does_not_propagate(caplog) -> None:
    pool, managers = make_pool(Managers(failing_stop=True))
    old = await pool.acquire()
    await pool.release(old)

    with caplog.at_level("WARNING"):
        await pool.swap(SECOND)
        await pool.close_all()

    assert all(m.stopped for m in managers.created)
    assert [r.message for r in caplog.records] == [
        "error al cerrar la generación 1 de MCPs: no se pudo cerrar",
        "error al cerrar la generación 2 de MCPs: no se pudo cerrar",
    ]


async def test_acquire_after_close_all_restarts_with_the_last_swapped_config() -> None:
    pool, managers = make_pool()
    await pool.swap(SECOND)
    await pool.close_all()

    generation = await pool.acquire()

    assert generation.tool_config == SECOND and managers.created[1].started_with == SECOND
    assert pool.current is generation


async def test_close_all_stops_every_generation_even_with_leases() -> None:
    pool, managers = make_pool()
    await pool.acquire()
    await pool.swap(SECOND)
    await pool.acquire()

    await asyncio.wait_for(pool.close_all(), 1)

    assert [m.stopped for m in managers.created] == [True, True]
    assert pool.current is None


async def test_manager_start_failure_leaves_no_current_generation() -> None:
    class Broken(FakeManager):
        async def start(self, tool_config, server_filter=None) -> None:
            raise RuntimeError("npx missing")

    pool = McpGenerationPool(lambda settings: Broken(), SETTINGS, FIRST)

    with pytest.raises(RuntimeError, match="npx missing"):
        await pool.acquire()

    assert pool.current is None
    await pool.close_all()


async def test_two_swaps_with_leases_keep_both_retired_generations_until_released() -> None:
    pool, managers = make_pool()
    first = await pool.acquire()
    second = await pool.swap(SECOND)
    second.leases += 1
    third = await pool.swap(FIRST)

    assert [g.id for g in (first, second, third)] == [1, 2, 3]
    assert [m.stopped for m in managers.created] == [False, False, False]
    await pool.release(second)
    assert [m.stopped for m in managers.created] == [False, True, False]
    await pool.release(first)
    assert [m.stopped for m in managers.created] == [True, True, False]
    await pool.close_all()
    assert managers.created[2].stopped is True


async def test_close_all_on_an_empty_pool_is_a_no_op() -> None:
    pool, managers = make_pool()

    await pool.close_all()

    assert managers.created == [] and pool.current is None


# --- serialisation of the first start, swaps and close -----------------------------------------


class BlockedFirstStart:
    """The first manager's start waits on `gate`; later managers start at once."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.created: list[FakeManager] = []

    def factory(self, settings) -> FakeManager:
        gate = self.gate if not self.created else None

        class Manager(FakeManager):
            async def start(self, tool_config, server_filter=None) -> None:
                if gate is not None:
                    await gate.wait()
                await super().start(tool_config, server_filter)

        manager = Manager()
        self.created.append(manager)
        return manager


async def test_late_initial_start_loses_against_a_swapped_generation() -> None:
    managers = BlockedFirstStart()
    pool = McpGenerationPool(managers.factory, SETTINGS, FIRST)
    first = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0)
    swapped = await asyncio.wait_for(pool.swap(SECOND), 1)
    assert pool.current is swapped and not first.done()

    managers.gate.set()
    leased = await asyncio.wait_for(first, 1)

    assert leased is swapped and swapped.tool_config == SECOND and swapped.leases == 1
    assert managers.created[0].started_with == FIRST
    assert [m.stopped for m in managers.created] == [True, False]
    await pool.close_all()
    assert [m.stopped for m in managers.created] == [True, True]


async def test_close_all_stops_a_start_in_flight_which_then_fails_to_publish() -> None:
    managers = BlockedFirstStart()
    pool = McpGenerationPool(managers.factory, SETTINGS, FIRST)
    first = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0)
    closing = asyncio.ensure_future(pool.close_all())
    await asyncio.sleep(0)

    managers.gate.set()
    await asyncio.wait_for(closing, 1)
    with pytest.raises(RuntimeError, match="se cerró durante el arranque"):
        await asyncio.wait_for(first, 1)

    assert pool.current is None
    assert managers.created[0].stopped is True


async def test_cancelled_acquire_during_start_publishes_nothing_and_stops_the_manager() -> None:
    managers = BlockedFirstStart()
    pool = McpGenerationPool(managers.factory, SETTINGS, FIRST)
    first = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    managers.gate.set()
    await asyncio.wait_for(pool.close_all(), 1)

    assert pool.current is None
    assert managers.created[0].stopped is True


async def test_swap_runs_on_publish_exactly_when_the_new_generation_becomes_current() -> None:
    pool, managers = make_pool()
    seen: list[ToolConfig | None] = []

    def on_publish() -> None:
        seen.append(pool.current.tool_config if pool.current else None)

    await pool.swap(SECOND, on_publish)

    assert seen == [SECOND]
    assert pool.current is not None and pool.current.tool_config == SECOND


async def test_lease_counts_on_the_given_generation_even_when_retired() -> None:
    pool, managers = make_pool()
    old = await pool.acquire()
    pool.lease(old)
    await pool.swap(SECOND)

    await pool.release(old)
    assert managers.created[0].stopped is False
    await pool.release(old)
    assert managers.created[0].stopped is True
