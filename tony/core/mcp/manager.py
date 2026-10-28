"""Owns the MCP client connections declared by an agent."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, CallToolResult

from tony.core.loader import HttpServer, StdioServer, ToolConfig
from tony.core.mcp.catalog import ToolCatalog
from tony.core.mcp.content import render_content
from tony.core.mcp.outcome import McpServerStatus, ToolCallOutcome

ServerSpec = StdioServer | HttpServer

logger = logging.getLogger(__name__)

UNKNOWN_OUTCOME = "; el resultado es desconocido, no repitas la llamada"
TRANSPORT_ERROR_CODES = frozenset({CONNECTION_CLOSED, REQUEST_TIMEOUT})
TRANSPORT_EXCEPTIONS = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    ConnectionError,
)


@dataclass
class _Connection:
    session: ClientSession
    stack: AsyncExitStack


class McpManager:
    def __init__(self, connect_timeout_s: float = 10) -> None:
        self._connect_timeout_s = connect_timeout_s
        self._connections: dict[str, _Connection] = {}
        self._errors: dict[str, str] = {}
        self._allow: list[str] | None = None
        self.catalog = ToolCatalog.empty()

    async def start(self, tool_config: ToolConfig, server_filter: list[str] | None = None) -> None:
        self._allow = tool_config.allow
        tools_by_server: dict[str, list[Any]] = {}
        for name, server in tool_config.mcpServers.items():
            if server_filter is not None and name not in server_filter:
                continue
            try:
                tools_by_server[name] = await self._connect(name, server)
            except Exception as exc:  # noqa: BLE001 - a broken server must not block the rest
                self._errors[name] = _describe(exc)
        self.catalog = ToolCatalog.build(tools_by_server, tool_config.allow, tool_config.confirm)
        for conflict in self.catalog.conflicts:
            logger.warning(conflict)

    async def call(self, qualified: str, args: dict[str, Any], timeout: float) -> ToolCallOutcome:
        ref = self.catalog.get(qualified)
        connection = self._connections.get(ref.server) if ref else None
        if ref is None or connection is None:
            return ToolCallOutcome.failure(f"tool {qualified} no permitida")
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                result = await connection.session.call_tool(ref.name, args)
        except TimeoutError:
            return ToolCallOutcome.failure(
                _timeout_message(qualified, timeout, ref.needs_confirm),
                duration_ms=_elapsed_ms(started),
                unknown=ref.needs_confirm,
            )
        except Exception as exc:  # noqa: BLE001 - any failure becomes a tool error
            unknown = ref.needs_confirm and _is_transport_failure(exc)
            return ToolCallOutcome.failure(
                _describe(exc) + (UNKNOWN_OUTCOME if unknown else ""),
                duration_ms=_elapsed_ms(started),
                unknown=unknown,
            )
        return _to_outcome(result, _elapsed_ms(started))

    def status(self) -> dict[str, McpServerStatus]:
        per_server = self.catalog.servers()
        statuses = {
            name: McpServerStatus(name, "ready", None, len(per_server.get(name, [])), self._allow)
            for name in self._connections
        }
        for name, error in self._errors.items():
            statuses[name] = McpServerStatus(name, "error", error, 0, self._allow)
        return statuses

    async def stop(self) -> None:
        connections, self._connections = self._connections, {}
        self.catalog = ToolCatalog.empty()
        for connection in reversed(list(connections.values())):
            try:
                await connection.stack.aclose()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass

    async def _connect(self, name: str, server: ServerSpec) -> list[Any]:
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(self._connect_timeout_s):
                read, write, *_ = await stack.enter_async_context(await _transport(server, stack))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
        except TimeoutError:
            await stack.aclose()
            raise TimeoutError(f"timeout de conexión tras {self._connect_timeout_s:g} s") from None
        except BaseException:
            await stack.aclose()
            raise
        self._connections[name] = _Connection(session, stack)
        return list(listed.tools)


async def _transport(server: ServerSpec, stack: AsyncExitStack):
    if isinstance(server, StdioServer):
        env = {**os.environ, **server.env} if server.env else None
        return stdio_client(
            StdioServerParameters(command=server.command, args=server.args, env=env)
        )
    # streamable_http_client does not own a caller-provided client, so the stack closes it
    # after the transport (reverse order of entry).
    client = await stack.enter_async_context(create_mcp_http_client(headers=server.headers))
    return streamable_http_client(server.url, http_client=client)


def _to_outcome(result: Any, duration_ms: int) -> ToolCallOutcome:
    if not isinstance(result, CallToolResult):
        return ToolCallOutcome.failure("respuesta MCP no soportada", duration_ms=duration_ms)
    content = render_content(result)
    if result.is_error:
        return ToolCallOutcome.failure(content or "error del servidor", duration_ms=duration_ms)
    return ToolCallOutcome(ok=True, content=content, duration_ms=duration_ms)


def _timeout_message(qualified: str, timeout: float, needs_confirm: bool) -> str:
    message = f"timeout tras {timeout:g} s en {qualified}"
    if needs_confirm:
        message += UNKNOWN_OUTCOME
    return message


def _is_transport_failure(exc: BaseException) -> bool:
    if isinstance(exc, MCPError):
        return exc.code in TRANSPORT_ERROR_CODES
    return isinstance(exc, TRANSPORT_EXCEPTIONS)


def _describe(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
