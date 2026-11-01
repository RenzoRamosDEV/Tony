"""Fake filesystem MCP server over stdio, rooted at the directory given as argv[1]."""

import asyncio
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

server = MCPServer("filesystem")
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()


def _resolve(path: str) -> Path:
    target = (ROOT / path).resolve()
    if ROOT not in (target, *target.parents):
        raise ToolError(f"path outside the allowed directory: {path}")
    return target


@server.tool(description="List the files of a directory.")
def list_directory(path: str = ".") -> str:
    folder = _resolve(path)
    if not folder.is_dir():
        raise ToolError(f"no such directory {path}")
    return "\n".join(sorted(entry.name for entry in folder.iterdir()))


@server.tool(description="Return the content of a file.")
def read_file(path: str) -> str:
    target = _resolve(path)
    if not target.is_file():
        raise ToolError(f"no such file {path}")
    return target.read_text(encoding="utf-8")


@server.tool(description="Write a file, replacing its content.")
def write_file(path: str, content: str) -> str:
    _resolve(path).write_text(content, encoding="utf-8")
    return f"written {path}"


@server.tool(description="Delete a file.")
def delete_file(path: str) -> str:
    target = _resolve(path)
    if not target.is_file():
        raise ToolError(f"no such file {path}")
    target.unlink()
    return f"deleted {path}"


@server.tool(description="Wait the given seconds, then answer.")
async def sleep(seconds: float) -> str:
    await asyncio.sleep(seconds)
    return "done"


@server.tool(description="Return the value of an environment variable.")
def echo_env(name: str) -> str:
    return os.environ.get(name, "")


if __name__ == "__main__":
    print(f"fake filesystem server serving {ROOT}", file=sys.stderr, flush=True)
    for name in filter(None, os.environ.get("ECHO_TO_STDERR", "").split(",")):
        print(f"{name}={os.environ.get(name, '')}", file=sys.stderr, flush=True)
    server.run("stdio")
