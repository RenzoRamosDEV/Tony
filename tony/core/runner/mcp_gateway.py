"""Stdio MCP gateway: exposes a `ToolCatalog` behind the same execution barrier.

Used by the `codex_cli` engine (design.md D4): Codex only talks to tools through MCP,
so `CodexCliRunner`/`CodexCliConversation` point `codex exec` at a subprocess built
from `build_gateway_server`, running over stdio (`run_stdio_gateway`). The handler
given to the gateway is whatever the caller wants behind it; in production this is a
`ToolBarrier.handler` bridged across the process boundary (see `gateway_bridge.py`),
so the allow/confirm/timeout/log barrier is never reimplemented for this transport.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import ServerRequestContext

from tony.core.mcp import ToolCatalog
from tony.core.runner.proxy import ToolReply

GATEWAY_NAME = "tony"
GATEWAY_VERSION = "1.0.0"
GatewayCaller = Callable[[str, dict[str, Any]], Awaitable[ToolReply]]


@dataclass(frozen=True)
class GatewayToolRef:
    """The subset of `ToolRef` the gateway needs to advertise a tool over MCP."""

    qualified: str
    name: str
    description: str
    input_schema: dict[str, Any]
    destructive: bool


def refs_from_catalog(catalog: ToolCatalog) -> list[GatewayToolRef]:
    return [
        GatewayToolRef(
            qualified=ref.qualified,
            name=ref.qualified,
            description=ref.description,
            input_schema=ref.input_schema,
            destructive=ref.destructive,
        )
        for ref in catalog.refs
    ]


def write_refs(path: Path, refs: list[GatewayToolRef]) -> None:
    payload = [
        {
            "qualified": ref.qualified,
            "name": ref.name,
            "description": ref.description,
            "input_schema": ref.input_schema,
            "destructive": ref.destructive,
        }
        for ref in refs
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_refs(path: Path) -> list[GatewayToolRef]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        GatewayToolRef(
            qualified=item["qualified"],
            name=item["name"],
            description=item["description"],
            input_schema=item["input_schema"],
            destructive=item["destructive"],
        )
        for item in payload
    ]


def build_gateway_server(refs: list[GatewayToolRef], call: GatewayCaller) -> Server:
    """Build the lowlevel MCP `Server` advertising `refs` and dispatching through `call`.

    `call` is transport-agnostic: in production it crosses a process boundary
    (`gateway_bridge.BridgeClient.call`), in tests it can be any async stand-in.
    """
    by_name = {ref.name: ref for ref in refs}

    async def on_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=ref.name,
                    description=ref.description,
                    inputSchema=ref.input_schema,
                    annotations=types.ToolAnnotations(destructiveHint=ref.destructive)
                    if ref.destructive
                    else None,
                )
                for ref in refs
            ]
        )

    async def on_call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        ref = by_name.get(params.name)
        if ref is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"tool {params.name} desconocida")],
                is_error=True,
            )
        reply = await call(ref.qualified, params.arguments or {})
        content = [
            types.TextContent(type="text", text=block["text"])
            for block in reply.get("content", [])
            if block.get("type") == "text"
        ]
        return types.CallToolResult(content=content, is_error=bool(reply.get("is_error", False)))

    return Server(
        GATEWAY_NAME,
        version=GATEWAY_VERSION,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def run_stdio_gateway(server: Server) -> None:
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
