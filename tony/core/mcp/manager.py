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
from mcp.types import CallToolResult, TextContent

from tony.core.config.placeholders import SecretMasker, resolve_placeholders
from tony.core.config.secrets import Variables
from tony.core.events import log_events
from tony.core.loader.tool_json import McpServer, ToolSpec
from tony.core.mcp.native import NATIVE_SERVER, NATIVE_TOOLS, NativeTool
from tony.core.orchestrator.ports import EventSink, ToolReply


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
        variables: Variables,
        masker: SecretMasker,
        sink: EventSink,
        log_dir: Path,
        connect_timeout: float = 10.0,
        native: Mapping[str, NativeTool] = NATIVE_TOOLS,
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
        self._sessions: dict[str, ClientSession] = {}
        self._native = {name: native[name] for name in spec.native}

    async def __aenter__(self) -> Self:
        for name, server in self.spec.mcp_servers.items():
            await self._start(name, server)
        self.tools += [
            CatalogTool(
                id=f"{NATIVE_SERVER}.{name}",
                server=NATIVE_SERVER,
                name=name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for name, tool in self._native.items()
        ]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        tool = next((tool for tool in self.tools if tool.id == tool_id), None)
        if tool is None:
            return ToolReply(text=f"tool {tool_id} is not available", is_error=True)
        if tool.server == NATIVE_SERVER:
            return ToolReply(text=await self._native[tool.name].run(args))
        result = await self._sessions[tool.server].call_tool(tool.name, args)
        return _to_reply(result)

    async def _start(self, name: str, declared: McpServer) -> None:
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(self.connect_timeout):
                session = await self._connect(name, declared, stack)
                listed = await session.list_tools()
        except Exception as error:
            await stack.aclose()
            self._mark_down(name, _describe(error, self.connect_timeout))
            return
        self._stack.push_async_callback(stack.aclose)
        self._sessions[name] = session
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

    async def _connect(
        self, name: str, declared: McpServer, stack: AsyncExitStack
    ) -> ClientSession:
        resolved, used = resolve_placeholders(
            declared.model_dump(exclude_unset=True), self._variables.values
        )
        secrets = used & self._variables.secret_names
        self._masker.register(self._variables.values[variable] for variable in secrets)
        server = McpServer.model_validate(resolved)
        transport = await self._transport(name, server, stack)
        read, write = await stack.enter_async_context(transport)
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

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


def _to_reply(result: CallToolResult) -> ToolReply:
    text = "\n".join(
        block.text if isinstance(block, TextContent) else f"[{block.type}]"
        for block in result.content
    )
    return ToolReply(text=text, is_error=bool(result.is_error))
