"""Unix-socket bridge forwarding gateway tool calls back to the owning process.

A `codex_cli` MCP gateway runs as its own OS process (one per task/turn, design.md
D4), so it cannot hold the parent's `ToolBarrier` Python object directly. `BridgeServer`
runs in the parent next to the real handler; `BridgeClient` runs inside the gateway
process and is the `GatewayCaller` handed to `build_gateway_server`. The wire format is
newline-delimited JSON request/response pairs over a Unix domain socket.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
from anyio.abc import SocketStream

from tony.core.runner.proxy import ToolReply

Handler = Callable[[str, dict[str, Any]], Awaitable[ToolReply]]


class BridgeServer:
    """Listens on `socket_path`, dispatching every request to `handler`."""

    def __init__(self, socket_path: Path, handler: Handler) -> None:
        self._socket_path = socket_path
        self._handler = handler
        self._listener: Any = None
        self._task_group: anyio.abc.TaskGroup | None = None

    async def __aenter__(self) -> BridgeServer:
        self._listener = await anyio.create_unix_listener(self._socket_path)
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._listener.serve, self._handle_connection)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._task_group is not None:
            self._task_group.cancel_scope.cancel()
            await self._task_group.__aexit__(*exc_info)
        if self._listener is not None:
            await self._listener.aclose()

    async def _handle_connection(self, stream: SocketStream) -> None:
        buffer = b""
        async with stream:
            while True:
                try:
                    chunk = await stream.receive()
                except anyio.EndOfStream:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    await self._respond(stream, line)

    async def _respond(self, stream: SocketStream, line: bytes) -> None:
        request = json.loads(line.decode("utf-8"))
        try:
            reply = await self._handler(request["qualified"], request["args"])
        except Exception as exc:  # noqa: BLE001 - every handler failure becomes a reply
            reply = {
                "content": [{"type": "text", "text": f"{exc.__class__.__name__}: {exc}"}],
                "is_error": True,
            }
        await stream.send(json.dumps(reply).encode("utf-8") + b"\n")


class BridgeClient:
    """Connects to a `BridgeServer` and exposes it as a `GatewayCaller`."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path
        self._stream: SocketStream | None = None
        self._buffer = b""

    async def __aenter__(self) -> BridgeClient:
        self._stream = await anyio.connect_unix(self._socket_path)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._stream is not None:
            await self._stream.aclose()

    async def call(self, qualified: str, args: dict[str, Any]) -> ToolReply:
        assert self._stream is not None, "BridgeClient no está conectado"
        request = json.dumps({"qualified": qualified, "args": args}).encode("utf-8") + b"\n"
        await self._stream.send(request)
        while b"\n" not in self._buffer:
            self._buffer += await self._stream.receive()
        line, self._buffer = self._buffer.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))
