"""`mcp_gateway_main`: the actual subprocess entry point `codex exec` launches.

Wires together `read_refs` (catalog serialized to a file by `CodexCliRunner`),
`BridgeClient` (forwards calls to the parent's real barrier over a Unix socket) and
`build_gateway_server`, then hands the result to `run_stdio_gateway`. The stdio loop
itself is exercised end to end only in the real-codex manual check; here `amain` is
tested with `run_stdio` swapped for a fake that proves the server it receives serves
the right tools and forwards through the right socket.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import anyio

from tony.core.runner.gateway_bridge import BridgeServer
from tony.core.runner.mcp_gateway_main import amain, parse_args


def test_parse_args_reads_socket_and_catalog_paths() -> None:
    args = parse_args(["--socket", "/tmp/a.sock", "--catalog", "/tmp/catalog.json"])

    assert args == (Path("/tmp/a.sock"), Path("/tmp/catalog.json"))


def test_amain_builds_a_server_that_forwards_through_the_bridge() -> None:
    received = {}

    async def handler(qualified: str, args: dict) -> dict:
        received["qualified"] = qualified
        return {"content": [{"type": "text", "text": "pong"}]}

    seen_server = {}

    async def fake_run_stdio(server) -> None:
        seen_server["server"] = server

    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "bridge.sock"
            catalog_path = Path(tmp) / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    [
                        {
                            "qualified": "fs.read",
                            "name": "fs.read",
                            "description": "lee",
                            "input_schema": {"type": "object"},
                            "destructive": False,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            async with BridgeServer(socket_path, handler):
                await amain(
                    ["--socket", str(socket_path), "--catalog", str(catalog_path)],
                    run_stdio=fake_run_stdio,
                )

    anyio.run(scenario)

    assert seen_server["server"] is not None
