"""Fake filesystem MCP server over stdio, rooted at the directory given as argument.

Run with: python -m tests.fakes.fake_filesystem_server <dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

server = MCPServer("filesystem")
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()


def _resolve(path: str) -> Path:
    target = (ROOT / path).resolve()
    if ROOT not in (target, *target.parents):
        raise ToolError(f"ruta fuera del directorio permitido: {path}")
    return target


@server.tool(description="Lista los ficheros de un directorio.")
def list_directory(path: str = ".") -> str:
    folder = _resolve(path)
    if not folder.is_dir():
        raise ToolError(f"no existe el directorio {path}")
    return "\n".join(sorted(p.name for p in folder.iterdir()))


@server.tool(description="Devuelve el contenido de un fichero.")
def read_file(path: str) -> str:
    target = _resolve(path)
    if not target.is_file():
        raise ToolError(f"no existe el fichero {path}")
    return target.read_text(encoding="utf-8")


@server.tool(description="Busca los ficheros cuyo contenido incluye el texto.")
def search_files(query: str) -> str:
    matches = sorted(
        str(p.relative_to(ROOT))
        for p in ROOT.rglob("*")
        if p.is_file() and query in p.read_text(encoding="utf-8", errors="ignore")
    )
    return "\n".join(matches) if matches else "(sin coincidencias)"


@server.tool(
    description="Escribe un fichero (sobrescribe si existe).",
    annotations=ToolAnnotations(destructiveHint=True),
)
def write_file(path: str, content: str) -> str:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"escrito {path}"


@server.tool(description="Siempre falla.")
def fail() -> str:
    raise ToolError("fallo simulado")


if __name__ == "__main__":
    server.run("stdio")
