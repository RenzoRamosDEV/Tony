"""Dependency rules from design.md D1: tony.core never depends on apps or frameworks."""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import tony.core

FORBIDDEN_IN_CORE = ("tony.apps", "typer", "fastapi")
SDK_ALLOWED_IN = {"tony.core.runner.claude_sdk", "tony.core.runner.proxy"}
MCP_CLIENT_ALLOWED_IN = {"tony.core.mcp.manager"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def core_modules() -> dict[str, set[str]]:
    result = {}
    for info in pkgutil.walk_packages(tony.core.__path__, prefix="tony.core."):
        path = Path(info.module_finder.path) / (info.name.rsplit(".", 1)[-1] + ".py")
        if path.is_file():
            result[info.name] = imported_modules(path)
    return result


def test_core_never_imports_apps_or_frameworks() -> None:
    offenders = {
        module: sorted(name for name in imports if name.startswith(FORBIDDEN_IN_CORE))
        for module, imports in core_modules().items()
    }
    assert {m: v for m, v in offenders.items() if v} == {}


def test_only_runner_adapters_import_the_agent_sdk() -> None:
    users = {
        m
        for m, imports in core_modules().items()
        if any(i.startswith("claude_agent_sdk") for i in imports)
    }
    assert users <= SDK_ALLOWED_IN


def test_only_mcp_manager_imports_mcp_client() -> None:
    users = {
        m
        for m, imports in core_modules().items()
        if any(i.startswith("mcp.client") for i in imports)
    }
    assert users <= MCP_CLIENT_ALLOWED_IN
