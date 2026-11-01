"""Fake shell-like MCP server over stdio; it only echoes, it never runs anything."""

import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("shell")


@server.tool(description="Pretend to run a shell command.")
def run(command: str) -> str:
    return f"ran {command}"


@server.tool(description="Answer bar.")
def bar() -> str:
    return "bar"


if __name__ == "__main__":
    print("fake shell server", file=sys.stderr, flush=True)
    server.run("stdio")
