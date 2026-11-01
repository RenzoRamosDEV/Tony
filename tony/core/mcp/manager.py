import asyncio
import sys
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from tony.core.config.placeholders import SecretMasker, resolve_placeholders
from tony.core.events import log_events
from tony.core.loader.tool_json import McpServer, ToolSpec
from tony.core.orchestrator.ports import EventSink


@dataclass(frozen=True)
class CatalogTool:
    id: str
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ServerStatus:
    up: bool
    reason: str | None = None


class McpManager:
    def __init__(
        self,
        spec: ToolSpec,
        *,
        variables: Mapping[str, str],
        masker: SecretMasker,
        sink: EventSink,
        log_dir: Path,
        connect_timeout: float = 10.0,
    ) -> None:
        self.spec = spec
        self.connect_timeout = connect_timeout
        self.tools: list[CatalogTool] = []
        self.status: dict[str, ServerStatus] = {}
        self._variables = variables
        self._masker = masker
        self._sink = sink
        self._log_dir = log_dir
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> Self:
        for name, server in self.spec.mcp_servers.items():
            await self._start(name, server)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def _start(self, name: str, declared: McpServer) -> None:
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(self.connect_timeout):
                listed = await self._connect(name, declared, stack)
        except Exception as error:
            await stack.aclose()
            self._mark_down(name, _describe(error, self.connect_timeout))
            return
        self._stack.push_async_callback(stack.aclose)
        self.tools += [
            CatalogTool(
                id=f"{name}.{tool.name}",
                server=name,
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
            )
            for tool in listed.tools
        ]
        self.status[name] = ServerStatus(up=True)

    async def _connect(self, name: str, declared: McpServer, stack: AsyncExitStack) -> Any:
        resolved, used = resolve_placeholders(
            declared.model_dump(exclude_unset=True), self._variables
        )
        self._masker.register(used)
        server = McpServer.model_validate(resolved)
        transport = await self._transport(name, server, stack)
        read, write = await stack.enter_async_context(transport)
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return await session.list_tools()

    async def _transport(self, name: str, server: McpServer, stack: AsyncExitStack) -> Any:
        if server.is_stdio:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            errlog = stack.enter_context((self._log_dir / f"{name}.log").open("a"))
            params = StdioServerParameters(
                command=server.command, args=server.args, env=server.env or None
            )
            return stdio_client(params, errlog)
        client = await stack.enter_async_context(create_mcp_http_client(headers=server.headers))
        return streamable_http_client(server.url, http_client=client)

    def _mark_down(self, name: str, reason: str) -> None:
        reason = self._masker.mask(reason)
        self.status[name] = ServerStatus(up=False, reason=reason)
        message = f"MCP server '{name}' is down: {reason}"
        self._sink.emit(log_events.error(f"mcp.{name}", message))
        print(f"tony: {message}", file=sys.stderr)


def _describe(error: BaseException, timeout: float) -> str:
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    if isinstance(error, TimeoutError):
        return f"connect timeout after {timeout:g} s"
    return str(error) or type(error).__name__
