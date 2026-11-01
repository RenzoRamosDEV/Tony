from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tony.core.config.placeholders import SecretMasker, resolve_placeholders
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
    ) -> None:
        self.spec = spec
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
        resolved, used = resolve_placeholders(
            declared.model_dump(exclude_unset=True), self._variables
        )
        self._masker.register(used)
        server = McpServer.model_validate(resolved)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        errlog = self._stack.enter_context((self._log_dir / f"{name}.log").open("a"))
        params = StdioServerParameters(
            command=server.command, args=server.args, env=server.env or None
        )
        read, write = await self._stack.enter_async_context(stdio_client(params, errlog))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
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
