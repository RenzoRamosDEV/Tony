import asyncio
import time
from types import SimpleNamespace

import pytest

from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager


class FakeSession:
    def __init__(self, name):
        self.name = name

    async def list_tools(self):
        tool = SimpleNamespace(name=f"{self.name}_tool", description="", input_schema={})
        return SimpleNamespace(tools=[tool])


class ScriptedServers(McpManager):
    """'script' maps a server to a delay or an exception; records who opens and closes it."""

    def __init__(self, *args, script, **kwargs):
        super().__init__(*args, **kwargs)
        self.script = script
        self.opened_by = {}
        self.closed_by = {}
        self.running = 0
        self.peak = 0

    async def _connect(self, name, declared, stack):
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            behaviour = self.script.get(name, 0)
            if isinstance(behaviour, Exception):
                raise behaviour
            await asyncio.sleep(behaviour)
        finally:
            self.running -= 1
        self.opened_by[name] = asyncio.current_task()
        stack.callback(lambda: self.closed_by.__setitem__(name, asyncio.current_task()))
        return FakeSession(name)


def build(tmp_path, names, script, **kwargs):
    spec = ToolSpec.model_validate({"mcpServers": {name: {"command": "x"} for name in names}})
    return ScriptedServers(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
        retry_delays=(),
        script=script,
        **kwargs,
    )


async def test_hanging_servers_start_within_one_timeout_window(tmp_path):
    names = ["a", "b", "c", "d"]
    manager = build(tmp_path, names, {name: 3600 for name in names}, connect_timeout=0.2)

    started = time.monotonic()
    async with manager:
        elapsed = time.monotonic() - started
        assert all(not manager.status[name].up for name in names)
        assert manager.tools == []

    assert elapsed < 0.2 * 2


async def test_catalog_keeps_declaration_order_whatever_connects_first(tmp_path):
    manager = build(tmp_path, ["a", "b"], {"a": 0.05, "b": 0})

    async with manager:
        assert [tool.id for tool in manager.tools] == ["a.a_tool", "b.b_tool"]


async def test_one_failure_does_not_stop_the_others(tmp_path):
    manager = build(tmp_path, ["a", "b", "c"], {"b": RuntimeError("boom")})

    async with manager:
        assert [tool.id for tool in manager.tools] == ["a.a_tool", "c.c_tool"]
        assert manager.status["b"].reason == "boom"


async def test_at_most_four_servers_connect_at_once(tmp_path):
    names = [f"s{i}" for i in range(7)]
    manager = build(tmp_path, names, {name: 0.01 for name in names})

    async with manager:
        assert len(manager.tools) == 7

    assert manager.peak == 4


async def test_each_connection_is_closed_by_the_task_that_opened_it(tmp_path):
    manager = build(tmp_path, ["a", "b"], {})

    async with manager:
        assert manager.closed_by == {}

    assert set(manager.closed_by) == {"a", "b"}
    assert manager.closed_by == manager.opened_by


async def test_cancelled_startup_closes_opened_connections_and_leaves_no_task(tmp_path):
    manager = build(tmp_path, ["a", "b"], {"a": 0, "b": 3600})
    before = asyncio.all_tasks()

    task = asyncio.create_task(manager.__aenter__())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert set(manager.closed_by) == {"a"}
    assert asyncio.all_tasks() - before == set()


async def test_status_lists_servers_in_declaration_order(tmp_path):
    manager = build(tmp_path, ["a", "b", "c"], {"a": 0.05, "b": RuntimeError("boom"), "c": 0})

    async with manager:
        assert list(manager.status) == ["a", "b", "c"]


async def test_cancelling_one_connection_task_aborts_startup(tmp_path):
    manager = build(tmp_path, ["a", "b"], {"a": 3600, "b": 3600})

    entering = asyncio.create_task(manager.__aenter__())
    await asyncio.sleep(0.02)
    manager._connections[0].cancel()

    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(2):
            await entering


async def test_no_settle_events_remain_after_exit(tmp_path):
    manager = build(tmp_path, ["a"], {"a": RuntimeError("boom")})
    manager.retry_delays = (0.0,)

    async with manager:
        await manager.wait_settled()

    assert manager._settled == []
