"""Dependency rules from design.md D1: tony.core never depends on apps or frameworks."""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import tony.core

FORBIDDEN_IN_CORE = ("tony.apps", "typer", "fastapi")
SDK_ALLOWED_IN = {
    "tony.core.runner.claude_sdk",
    "tony.core.runner.proxy",
    "tony.core.runner.conversation",
    "tony.core.runner.native_tools",
}
MCP_CLIENT_ALLOWED_IN = {"tony.core.mcp.manager"}
SQLITE_ALLOWED_IN = {"tony.core.memory.conversations"}
WORKER_PATH_PACKAGES = ("tony.core.runner.", "tony.core.orchestrator.", "tony.core.memory.")
CHANNELS_PACKAGE = "tony.core.channels"


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


def offenders(modules: dict[str, set[str]], forbidden: tuple[str, ...]) -> dict[str, list[str]]:
    found = {
        module: sorted(name for name in imports if name.startswith(forbidden))
        for module, imports in modules.items()
    }
    return {module: names for module, names in found.items() if names}


def users_of(modules: dict[str, set[str]], prefix: str) -> set[str]:
    return {m for m, imports in modules.items() if any(i.startswith(prefix) for i in imports)}


def worker_path_offenders(modules: dict[str, set[str]]) -> dict[str, list[str]]:
    worker_side = {m: i for m, i in modules.items() if m.startswith(WORKER_PATH_PACKAGES)}
    return offenders(worker_side, (CHANNELS_PACKAGE,))


def test_core_never_imports_apps_or_frameworks() -> None:
    assert offenders(core_modules(), FORBIDDEN_IN_CORE) == {}


def test_only_runner_adapters_import_the_agent_sdk() -> None:
    assert users_of(core_modules(), "claude_agent_sdk") <= SDK_ALLOWED_IN


def test_only_mcp_manager_imports_mcp_client() -> None:
    assert users_of(core_modules(), "mcp.client") <= MCP_CLIENT_ALLOWED_IN


def test_only_conversations_store_imports_sqlite() -> None:
    assert users_of(core_modules(), "sqlite3") == SQLITE_ALLOWED_IN


def test_worker_path_never_imports_channels() -> None:
    assert worker_path_offenders(core_modules()) == {}


def test_a_simulated_forbidden_import_is_reported() -> None:
    simulated = {
        "tony.core.runner.claude_sdk": {"asyncio", "tony.core.channels.ports"},
        "tony.core.orchestrator.orchestrator": {"tony.core.channels"},
        "tony.core.memory.settings": {"json"},
        "tony.core.channels.session": {"tony.core.channels.ports"},
    }

    assert worker_path_offenders(simulated) == {
        "tony.core.runner.claude_sdk": ["tony.core.channels.ports"],
        "tony.core.orchestrator.orchestrator": ["tony.core.channels"],
    }
    assert offenders({"tony.core.x": {"typer", "os"}}, FORBIDDEN_IN_CORE) == {
        "tony.core.x": ["typer"]
    }
    assert users_of({"tony.core.y": {"sqlite3"}}, "sqlite3") == {"tony.core.y"}
