"""`build_gateway_server`: exposes a ToolCatalog behind the same barrier semantics.

Driven over mcp's in-memory client/server streams (no real stdio/subprocess needed to
prove the MCP-level behavior): list_tools reflects the catalog, call_tool dispatches
through the given `call`, and an unknown tool name is rejected with `is_error=True`
instead of crashing the gateway, exactly like `ToolBarrier` already does for
`claude_sdk`.
"""

from __future__ import annotations

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from tony.core.mcp import ToolCatalog
from tony.core.mcp.catalog import ToolRef
from tony.core.runner.mcp_gateway import build_gateway_server, refs_from_catalog


def make_catalog() -> ToolCatalog:
    ref = ToolRef(
        server="filesystem",
        name="read_file",
        qualified="filesystem.read_file",
        description="Lee un fichero",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        destructive=False,
        needs_confirm=False,
    )
    return ToolCatalog.from_refs([ref])


async def _serve_and_connect(server, client_coro):
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                await server.run(
                    server_streams[0], server_streams[1], server.create_initialization_options()
                )

            tg.start_soon(run_server)
            async with ClientSession(client_streams[0], client_streams[1]) as session:
                await session.initialize()
                await client_coro(session)
            tg.cancel_scope.cancel()


def test_list_tools_reflects_the_catalog() -> None:
    catalog = make_catalog()
    refs = refs_from_catalog(catalog)

    async def noop_call(qualified: str, args: dict) -> dict:
        raise AssertionError("no debería llamarse para list_tools")

    server = build_gateway_server(refs, noop_call)
    seen = {}

    async def list_tools(session: ClientSession) -> None:
        result = await session.list_tools()
        seen["names"] = [tool.name for tool in result.tools]

    anyio.run(_serve_and_connect, server, list_tools)

    assert seen["names"] == ["filesystem.read_file"]


def test_call_tool_dispatches_through_the_given_caller() -> None:
    catalog = make_catalog()
    refs = refs_from_catalog(catalog)
    received = {}

    async def call(qualified: str, args: dict) -> dict:
        received["qualified"] = qualified
        received["args"] = args
        return {"content": [{"type": "text", "text": "contenido del fichero"}]}

    server = build_gateway_server(refs, call)
    seen = {}

    async def call_tool(session: ClientSession) -> None:
        result = await session.call_tool("filesystem.read_file", {"path": "a.txt"})
        seen["text"] = result.content[0].text
        seen["is_error"] = result.is_error

    anyio.run(_serve_and_connect, server, call_tool)

    assert received == {"qualified": "filesystem.read_file", "args": {"path": "a.txt"}}
    assert seen == {"text": "contenido del fichero", "is_error": False}


def test_call_tool_rejects_an_unknown_tool_without_crashing() -> None:
    server = build_gateway_server([], lambda qualified, args: None)
    seen = {}

    async def call_tool(session: ClientSession) -> None:
        result = await session.call_tool("ghost.tool", {})
        seen["is_error"] = result.is_error
        seen["text"] = result.content[0].text

    anyio.run(_serve_and_connect, server, call_tool)

    assert seen["is_error"] is True
    assert "ghost.tool" in seen["text"]
