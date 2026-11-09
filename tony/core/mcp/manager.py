import asyncio
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
from tony.core.mcp.native import NATIVE_SERVER, NativeTool
from tony.core.mcp.stderr import MaskedStderr
from tony.core.orchestrator.ports import EventSink, ToolReply

DEFAULT_RETRY_DELAYS = (5.0, 15.0, 30.0)
MAX_CONCURRENT_CONNECTIONS = 4


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


StatusCallback = Callable[[str, ServerStatus], None]


class McpManager:
    def __init__(
        self,
        spec: ToolSpec,
        *,
        variables: Variables,
        masker: SecretMasker,
        sink: EventSink,
        log_dir: Path,
        connect_timeout: float = 30.0,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        native: Mapping[str, NativeTool] | None = None,
        on_status: StatusCallback = lambda server, status: None,
    ) -> None:
        self.spec = spec
        self.connect_timeout = connect_timeout
        self.retry_delays = tuple(retry_delays)
        self.tools: list[CatalogTool] = []
        self.status: dict[str, ServerStatus] = {}
        self._variables = variables
        self._masker = masker
        self._sink = sink
        self._log_dir = log_dir
        self._closing = asyncio.Event()
        self._connections: list[asyncio.Task[None]] = []
        self._sessions: dict[str, ClientSession] = {}
        self._native = {name: tool for name, tool in (native or {}).items() if name in spec.native}
        self._on_status = on_status
        self._sleep = sleep
        self._retries: set[asyncio.Task[None]] = set()
        self._settled: list[asyncio.Event] = []

    async def __aenter__(self) -> Self:
        gate = asyncio.Semaphore(MAX_CONCURRENT_CONNECTIONS)
        loop = asyncio.get_running_loop()
        started = [loop.create_future() for _ in self.spec.mcp_servers]
        self._connections = [
            asyncio.create_task(self._hold_connection(name, server, gate, future))
            for (name, server), future in zip(self.spec.mcp_servers.items(), started, strict=True)
        ]
        try:
            declared_tools = await asyncio.gather(*started)
        except BaseException:
            await self._close(cancel=True)
            raise
        for tools in declared_tools:
            self.tools += tools
        self.status = {name: self.status[name] for name in self.spec.mcp_servers}
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
        await self._close(cancel=False)

    async def _close(self, *, cancel: bool) -> None:
        await self._cancel_retries()
        self._closing.set()
        if cancel:
            for connection in self._connections:
                connection.cancel()
        await asyncio.gather(*self._connections, return_exceptions=True)
        self._connections.clear()

    async def wait_settled(self) -> None:
        """Returns once every failed server has recovered or exhausted its retries."""
        await asyncio.gather(*(event.wait() for event in self._settled))

    async def _cancel_retries(self) -> None:
        tasks = list(self._retries)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._retries.clear()
        self._settled.clear()

    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        tool = next((tool for tool in self.tools if tool.id == tool_id), None)
        if tool is None:
            return ToolReply(text=f"tool {tool_id} is not available", is_error=True)
        if tool.server == NATIVE_SERVER:
            return await self._native[tool.name].run(args)
        result = await self._sessions[tool.server].call_tool(tool.name, args)
        return _to_reply(result)

    async def _hold_connection(
        self,
        name: str,
        declared: McpServer,
        gate: asyncio.Semaphore,
        started: asyncio.Future[list[CatalogTool]],
    ) -> None:
        """Owns the connection it opens: closing it in the same task keeps anyio scopes valid."""
        stack = AsyncExitStack()
        try:
            async with gate:
                tools = await self._start(name, declared, stack)
            started.set_result(tools)
            await self._closing.wait()
        except asyncio.CancelledError:
            started.cancel()
            raise
        except BaseException as error:
            if not started.done():
                started.set_exception(error)
            raise
        finally:
            await stack.aclose()

    async def _start(
        self, name: str, declared: McpServer, stack: AsyncExitStack
    ) -> list[CatalogTool]:
        try:
            return await self._attempt(name, declared, stack)
        except Exception as error:
            await stack.aclose()
            self._mark_down(name, _describe(error, self.connect_timeout))
            if self.retry_delays:
                settled = asyncio.Event()
                self._settled.append(settled)
                task = asyncio.create_task(self._retry(name, declared, settled))
                self._retries.add(task)
                task.add_done_callback(self._retries.discard)
            return []

    async def _attempt(
        self, name: str, declared: McpServer, stack: AsyncExitStack
    ) -> list[CatalogTool]:
        async with asyncio.timeout(self.connect_timeout):
            session = await self._connect(name, declared, stack)
            listed = await session.list_tools()
        self._sessions[name] = session
        tools = [
            CatalogTool(
                id=f"{name}.{tool.name}",
                server=name,
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
            )
            for tool in listed.tools
        ]
        self._set_status(name, ServerStatus(up=True))
        return tools

    async def _retry(self, name: str, declared: McpServer, settled: asyncio.Event) -> None:
        """Owns the connection it opens: closing it in the same task keeps anyio scopes valid."""
        try:
            await self._retry_until_connected(name, declared, settled)
        finally:
            settled.set()

    async def _retry_until_connected(
        self, name: str, declared: McpServer, settled: asyncio.Event
    ) -> None:
        for delay in self.retry_delays:
            await self._sleep(delay)
            stack = AsyncExitStack()
            try:
                tools = await self._attempt(name, declared, stack)
            except Exception as error:
                await stack.aclose()
                reason = self._masker.mask(_describe(error, self.connect_timeout))
                if self.status[name].reason != reason:
                    self._mark_down(name, reason)
                continue
            except BaseException:
                await stack.aclose()
                raise
            self.tools += tools
            settled.set()
            try:
                await asyncio.Event().wait()
            finally:
                await stack.aclose()

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
            errlog = stack.enter_context(MaskedStderr(self._log_dir / f"{name}.log", self._masker))
            params = StdioServerParameters(
                command=stdio_command(server.command), args=server.args, env=server.env or None
            )
            return stdio_client(params, errlog)
        client = await stack.enter_async_context(create_mcp_http_client(headers=server.headers))
        return streamable_http_client(server.url, http_client=client)

    def _set_status(self, name: str, status: ServerStatus) -> None:
        self.status[name] = status
        self._on_status(name, status)

    def _mark_down(self, name: str, reason: str) -> None:
        reason = self._masker.mask(reason)
        self._set_status(name, ServerStatus(up=False, reason=reason))
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


def stdio_command(declared: str) -> str:
    """A bare ``python`` must run with Tony's own interpreter, not whatever is on PATH."""
    return sys.executable if declared in _BARE_PYTHON else declared


_BARE_PYTHON = frozenset({"python", "python3"})
