"""Sanity check for the fake stdio MCP server used across the suite."""

from __future__ import annotations

import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def test_fake_server_lists_four_tools_and_marks_destroy() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "tests.fakes.fake_mcp_server"]
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        echoed = await session.call_tool("echo", {"text": "hola"})
        failed = await session.call_tool("fail", {})

    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == {"echo", "fail", "slow", "destroy"}
    assert tools["destroy"].annotations.destructive_hint is True
    assert tools["echo"].annotations is None
    assert tools["echo"].input_schema["properties"]["text"]["type"] == "string"
    assert echoed.is_error is False
    assert echoed.content[0].text == "hola"
    assert failed.is_error is True
