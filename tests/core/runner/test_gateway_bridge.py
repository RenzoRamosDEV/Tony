"""BridgeServer/BridgeClient: cross-process forwarding of one `GatewayCaller`.

`CodexCliRunner` spawns the `mcp-gateway` subprocess per task/turn; that subprocess
cannot share the parent's `ToolBarrier` Python object, so it forwards every tool call
over a Unix domain socket back to a `BridgeServer` the parent runs against the real
barrier handler. These tests prove the round trip (request in, handler's reply out)
and that a handler exception becomes an error reply instead of killing the bridge.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import anyio

from tony.core.runner.gateway_bridge import BridgeClient, BridgeServer


def test_round_trips_a_call_to_the_bound_handler() -> None:
    received = {}

    async def handler(qualified: str, args: dict) -> dict:
        received["qualified"] = qualified
        received["args"] = args
        return {"content": [{"type": "text", "text": "ok"}]}

    async def scenario() -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "bridge.sock"
            async with BridgeServer(socket_path, handler):
                async with BridgeClient(socket_path) as client:
                    return await client.call("filesystem.read_file", {"path": "a.txt"})

    reply = anyio.run(scenario)

    assert received == {"qualified": "filesystem.read_file", "args": {"path": "a.txt"}}
    assert reply == {"content": [{"type": "text", "text": "ok"}]}


def test_a_handler_exception_becomes_an_error_reply_not_a_crash() -> None:
    async def handler(qualified: str, args: dict) -> dict:
        raise RuntimeError("boom")

    async def scenario() -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "bridge.sock"
            async with BridgeServer(socket_path, handler):
                async with BridgeClient(socket_path) as client:
                    return await client.call("x.y", {})

    reply = anyio.run(scenario)

    assert reply["is_error"] is True
    assert "boom" in reply["content"][0]["text"]


def test_several_calls_round_trip_over_the_same_connection() -> None:
    calls = []

    async def handler(qualified: str, args: dict) -> dict:
        calls.append(qualified)
        return {"content": [{"type": "text", "text": qualified}]}

    async def scenario() -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "bridge.sock"
            async with BridgeServer(socket_path, handler):
                async with BridgeClient(socket_path) as client:
                    return [await client.call(name, {}) for name in ("a.b", "c.d")]

    replies = anyio.run(scenario)

    assert calls == ["a.b", "c.d"]
    assert [r["content"][0]["text"] for r in replies] == ["a.b", "c.d"]
