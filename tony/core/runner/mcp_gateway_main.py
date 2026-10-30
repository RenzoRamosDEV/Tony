"""Entry point `python -m tony.core.runner.mcp_gateway_main` run by `codex exec`.

`CodexCliRunner`/`CodexCliConversation` point Codex's `mcp_servers.tony.command`/
`args` at this module (via `-c mcp_servers.tony.command=...`, design.md D4). It
rebuilds the task's `ToolCatalog` from the file `CodexCliRunner` serialized with
`write_refs`, forwards every tool call to the parent process over `BridgeClient`, and
serves the result over stdio to Codex.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from mcp.server.lowlevel import Server

from tony.core.runner.gateway_bridge import BridgeClient
from tony.core.runner.mcp_gateway import build_gateway_server, read_refs, run_stdio_gateway

RunStdio = Callable[[Server], Awaitable[None]]


def parse_args(argv: list[str]) -> tuple[Path, Path]:
    values: dict[str, str] = {}
    pending = list(argv)
    while pending:
        flag = pending.pop(0)
        if flag in ("--socket", "--catalog") and pending:
            values[flag.removeprefix("--")] = pending.pop(0)
    return Path(values["socket"]), Path(values["catalog"])


async def amain(argv: list[str], run_stdio: RunStdio = run_stdio_gateway) -> None:
    socket_path, catalog_path = parse_args(argv)
    refs = read_refs(catalog_path)
    async with BridgeClient(socket_path) as client:
        server = build_gateway_server(refs, client.call)
        await run_stdio(server)


def main(argv: list[str] | None = None) -> int:
    import anyio

    anyio.run(amain, argv if argv is not None else sys.argv[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
