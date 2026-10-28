"""Fake MCP server used by the test suite over stdio (no network).

Run with: python -m tests.fakes.fake_mcp_server
"""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

server = MCPServer("fake")


@server.tool(description="Devuelve el texto recibido.")
def echo(text: str) -> str:
    return text


@server.tool(description="Siempre falla.")
def fail() -> str:
    raise ToolError("fallo simulado")


@server.tool(description="Tarda el tiempo indicado.")
async def slow(seconds: float = 25) -> str:
    await asyncio.sleep(seconds)
    return "hecho"


@server.tool(
    description="Operación destructiva.", annotations=ToolAnnotations(destructiveHint=True)
)
def destroy() -> str:
    return "destruido"


if __name__ == "__main__":
    server.run("stdio")
