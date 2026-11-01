import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import uvicorn
from mcp.server.mcpserver import MCPServer


@dataclass
class RunningHttpServer:
    url: str
    authorizations: list[str] = field(default_factory=list)


def _build_mcp_server() -> MCPServer:
    server = MCPServer("remote")

    @server.tool(description="Answer pong.")
    def ping() -> str:
        return "pong"

    @server.tool()
    def bare() -> str:
        return "no description"

    return server


@asynccontextmanager
async def running_http_mcp_server():
    """Serve a streamable-HTTP MCP server with a `ping` tool on an ephemeral local port."""
    app = _build_mcp_server().streamable_http_app()
    recorded = RunningHttpServer(url="")

    async def recording_app(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            recorded.authorizations.append(headers.get(b"authorization", b"").decode())
        await app(scope, receive, send)

    server = uvicorn.Server(
        uvicorn.Config(recording_app, host="127.0.0.1", port=0, log_level="error")
    )
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    recorded.url = f"http://127.0.0.1:{port}/mcp"
    try:
        yield recorded
    finally:
        server.should_exit = True
        await serving
