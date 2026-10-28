"""Integration tests for McpManager against the fake stdio MCP server."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator

from tony.core.loader import StdioServer, ToolConfig
from tony.core.mcp import McpManager

FAKE = StdioServer(command=sys.executable, args=["-m", "tests.fakes.fake_mcp_server"])
BROKEN = StdioServer(command="/no/existe")
CONNECT_TIMEOUT = 5.0


async def started(config: ToolConfig, server_filter=None) -> AsyncIterator[McpManager]:
    manager = McpManager(connect_timeout_s=CONNECT_TIMEOUT)
    await manager.start(config, server_filter=server_filter)
    try:
        yield manager
    finally:
        await manager.stop()


def fake_only() -> AsyncIterator[McpManager]:
    return started(ToolConfig(mcpServers={"fake": FAKE}))


async def test_stdio_server_is_ready_with_four_tools() -> None:
    async for manager in fake_only():
        status = manager.status()["fake"]
        catalog_size = len(manager.catalog)

    assert status.state == "ready"
    assert status.tool_count == 4
    assert status.error is None
    assert status.allow is None
    assert catalog_size == 4


async def test_server_filter_connects_only_selected() -> None:
    config = ToolConfig(mcpServers={"fake": FAKE, "notion": BROKEN})
    async for manager in started(config, server_filter=["fake"]):
        assert set(manager.status()) == {"fake"}
        assert manager.status()["fake"].state == "ready"


async def test_broken_server_does_not_block_the_others() -> None:
    config = ToolConfig(mcpServers={"fake": FAKE, "broken": BROKEN})
    async for manager in started(config):
        status = manager.status()
        assert status["broken"].state == "error"
        assert status["broken"].error
        assert status["broken"].tool_count == 0
        assert status["fake"].state == "ready"
        assert status["fake"].tool_count == 4


async def test_all_servers_down_yields_empty_catalog_without_raising() -> None:
    async for manager in started(ToolConfig(mcpServers={"broken": BROKEN})):
        assert len(manager.catalog) == 0
        assert manager.status()["broken"].state == "error"


async def test_echo_call_succeeds() -> None:
    async for manager in fake_only():
        outcome = await manager.call("fake.echo", {"text": "hola"}, timeout=5)

    assert outcome.ok is True
    assert "hola" in outcome.content
    assert outcome.error is None
    assert outcome.duration_ms >= 0
    assert outcome.outcome_unknown is False


async def test_failing_tool_reports_server_error() -> None:
    async for manager in fake_only():
        outcome = await manager.call("fake.fail", {}, timeout=5)

    assert outcome.ok is False
    assert "fallo simulado" in outcome.error
    assert outcome.outcome_unknown is False


async def test_timeout_on_non_destructive_tool() -> None:
    async for manager in fake_only():
        outcome = await manager.call("fake.slow", {"seconds": 2}, timeout=0.5)

    assert outcome.ok is False
    assert "timeout" in outcome.error
    assert "0.5" in outcome.error
    assert outcome.outcome_unknown is False


async def test_timeout_on_destructive_tool_is_unknown_outcome() -> None:
    config = ToolConfig(mcpServers={"fake": FAKE}, confirm=["fake.slow"])
    async for manager in started(config):
        outcome = await manager.call("fake.slow", {"seconds": 2}, timeout=0.5)

    assert outcome.ok is False
    assert outcome.outcome_unknown is True
    assert "desconocido" in outcome.error


async def test_tool_outside_catalog_is_rejected_before_reaching_server() -> None:
    config = ToolConfig(mcpServers={"fake": FAKE}, allow=["fake.echo"])
    async for manager in started(config):
        outcome = await manager.call("fake.destroy", {}, timeout=5)

    assert outcome.ok is False
    assert "no permitida" in outcome.error
    assert outcome.outcome_unknown is False


async def test_status_reports_effective_allow() -> None:
    config = ToolConfig(mcpServers={"fake": FAKE}, allow=["fake.echo", "fake.slow"])
    async for manager in started(config):
        status = manager.status()["fake"]

    assert status.state == "ready"
    assert status.tool_count == 2
    assert status.allow == ["fake.echo", "fake.slow"]


async def test_stop_terminates_server_and_rejects_further_calls() -> None:
    manager = McpManager(connect_timeout_s=CONNECT_TIMEOUT)
    await manager.start(ToolConfig(mcpServers={"fake": FAKE}))
    await manager.stop()

    outcome = await manager.call("fake.echo", {"text": "x"}, timeout=5)

    assert outcome.ok is False
    assert len(manager.catalog) == 0
