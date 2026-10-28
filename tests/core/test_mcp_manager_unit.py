"""Unit tests for McpManager with in-process transport and session doubles."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, INVALID_PARAMS, REQUEST_TIMEOUT, Tool

from tony.core.loader import HttpServer, StdioServer, ToolConfig
from tony.core.mcp import manager as manager_module
from tony.core.mcp.manager import McpManager


def mcp_tool(name: str) -> Tool:
    return Tool(name=name, inputSchema={"type": "object", "properties": {}})


class FakeSession:
    def __init__(self, tools: list[Tool], error: Exception | None = None) -> None:
        self.tools = tools
        self.error = error

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> Any:
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        raise self.error or RuntimeError("no scripted result")


@asynccontextmanager
async def stdio_transport_named_by_command(params: Any):
    yield params.command, params.command


def install_fakes(monkeypatch: pytest.MonkeyPatch, sessions: dict[str, FakeSession]) -> None:
    monkeypatch.setattr(manager_module, "stdio_client", stdio_transport_named_by_command)
    monkeypatch.setattr(manager_module, "ClientSession", lambda read, write: sessions[read])


def stdio(name: str) -> StdioServer:
    return StdioServer(command=name)


@pytest.mark.parametrize(
    ("error", "unknown"),
    [
        (MCPError(code=CONNECTION_CLOSED, message="Connection closed"), True),
        (MCPError(code=REQUEST_TIMEOUT, message="Request timed out"), True),
        (anyio.BrokenResourceError(), True),
        (anyio.ClosedResourceError(), True),
        (ConnectionResetError("reset"), True),
        (MCPError(code=INVALID_PARAMS, message="bad args"), False),
        (RuntimeError("boom"), False),
    ],
)
async def test_transport_failure_on_confirm_tool_is_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch, error: Exception, unknown: bool
) -> None:
    install_fakes(monkeypatch, {"fake": FakeSession([mcp_tool("write")], error=error)})
    manager = McpManager()
    await manager.start(ToolConfig(mcpServers={"fake": stdio("fake")}, confirm=["fake.write"]))

    outcome = await manager.call("fake.write", {}, timeout=1)

    assert outcome.ok is False
    assert outcome.outcome_unknown is unknown
    assert ("no repitas la llamada" in outcome.error) is unknown


async def test_transport_failure_on_plain_tool_is_a_known_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = MCPError(code=CONNECTION_CLOSED, message="Connection closed")
    install_fakes(monkeypatch, {"fake": FakeSession([mcp_tool("read")], error=error)})
    manager = McpManager()
    await manager.start(ToolConfig(mcpServers={"fake": stdio("fake")}))

    outcome = await manager.call("fake.read", {}, timeout=1)

    assert outcome.outcome_unknown is False
    assert outcome.error == "Connection closed"


async def test_http_client_is_closed_together_with_the_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = []
    real_create = manager_module.create_mcp_http_client

    def create(headers=None):
        client = real_create(headers=headers)
        created.append(client)
        return client

    received: dict[str, Any] = {}

    @asynccontextmanager
    async def http_transport(url: str, http_client: Any = None, **kwargs: Any):
        received["client"] = http_client
        yield "n", "n"

    monkeypatch.setattr(manager_module, "create_mcp_http_client", create)
    monkeypatch.setattr(manager_module, "streamable_http_client", http_transport)
    monkeypatch.setattr(manager_module, "ClientSession", lambda read, write: FakeSession([]))
    manager = McpManager()
    await manager.start(ToolConfig(mcpServers={"n": HttpServer(url="http://localhost:1/mcp")}))

    assert received["client"] is created[0]
    assert created[0].is_closed is False
    await manager.stop()
    assert created[0].is_closed is True


async def test_http_client_is_closed_when_the_transport_fails_to_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = []
    real_create = manager_module.create_mcp_http_client

    def create(headers=None):
        client = real_create(headers=headers)
        created.append(client)
        return client

    @asynccontextmanager
    async def refusing_transport(url: str, http_client: Any = None, **kwargs: Any):
        raise ConnectionError("connection refused")
        yield

    monkeypatch.setattr(manager_module, "create_mcp_http_client", create)
    monkeypatch.setattr(manager_module, "streamable_http_client", refusing_transport)
    manager = McpManager()
    await manager.start(ToolConfig(mcpServers={"n": HttpServer(url="http://localhost:1/mcp")}))

    assert manager.status()["n"].state == "error"
    assert created[0].is_closed is True


async def test_qualified_name_conflicts_are_logged_as_warnings(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install_fakes(
        monkeypatch, {"a": FakeSession([mcp_tool("b.c")]), "a.b": FakeSession([mcp_tool("c")])}
    )
    manager = McpManager()

    with caplog.at_level(logging.WARNING, logger="tony.core.mcp.manager"):
        await manager.start(ToolConfig(mcpServers={"a": stdio("a"), "a.b": stdio("a.b")}))

    assert manager.catalog.qualified_names() == ["a.b.c"]
    assert [r.getMessage() for r in caplog.records] == list(manager.catalog.conflicts)
