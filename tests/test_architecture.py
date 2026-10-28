"""Dependency rules from design.md D1: tony.core never depends on apps or frameworks."""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path
from typing import Any

import tony.apps
import tony.core

FORBIDDEN_IN_CORE = ("tony.apps", "typer", "fastapi")
SDK_ALLOWED_IN = {
    "tony.core.runner.claude_sdk",
    "tony.core.runner.proxy",
    "tony.core.runner.conversation",
    "tony.core.runner.native_tools",
    "tony.core.runner.oneshot",
}
MCP_CLIENT_ALLOWED_IN = {"tony.core.mcp.manager"}
WATCHFILES_ALLOWED_IN = {"tony.core.config.watcher"}
FRAMEWORK_FREE_PACKAGES = (
    "tony.core.skills.",
    "tony.core.subagents.",
    "tony.core.doctor.",
    "tony.core.evals.",
    "tony.core.voice.",
)
FORBIDDEN_IN_FRAMEWORK_FREE = ("tony.core.channels", "pytest", "typer")
SQLITE_ALLOWED_IN = {"tony.core.memory.conversations"}
WORKER_PATH_PACKAGES = ("tony.core.runner.", "tony.core.orchestrator.", "tony.core.memory.")
CHANNELS_PACKAGE = "tony.core.channels"
WEB_FRAMEWORKS = ("fastapi", "starlette", "uvicorn")
WEB_PACKAGE = "tony.apps.web."
CLI_PACKAGE = "tony.apps.cli"
ENGINE_MODULES = ("faster_whisper", "kokoro", "silero_vad", "onnxruntime", "torch")
ENGINES_PACKAGE = "tony.core.voice.engines"
VOICE_ADAPTERS = ("tony.apps.web.audio_ws", "tony.apps.web.tts_stream")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _modules_of(package: Any, prefix: str) -> dict[str, set[str]]:
    """Imports of every module and package `__init__` under `package`, keyed by dotted name."""
    result = {}
    for info in pkgutil.walk_packages(package.__path__, prefix=prefix):
        leaf = info.name.rsplit(".", 1)[-1]
        folder = Path(info.module_finder.path)
        path = folder / leaf / "__init__.py" if info.ispkg else folder / f"{leaf}.py"
        if path.is_file():
            result[info.name] = imported_modules(path)
    return result


def core_modules() -> dict[str, set[str]]:
    return _modules_of(tony.core, "tony.core.")


def apps_modules() -> dict[str, set[str]]:
    return _modules_of(tony.apps, "tony.apps.")


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


def framework_free_offenders(modules: dict[str, set[str]]) -> dict[str, list[str]]:
    scoped = {m: i for m, i in modules.items() if m.startswith(FRAMEWORK_FREE_PACKAGES)}
    return offenders(scoped, FORBIDDEN_IN_FRAMEWORK_FREE)


def web_framework_offenders(modules: dict[str, set[str]]) -> dict[str, list[str]]:
    outside_web = {m: i for m, i in modules.items() if not m.startswith(WEB_PACKAGE)}
    return offenders(outside_web, WEB_FRAMEWORKS)


def web_to_cli_offenders(modules: dict[str, set[str]]) -> dict[str, list[str]]:
    web = {m: i for m, i in modules.items() if m.startswith(WEB_PACKAGE)}
    return offenders(web, (CLI_PACKAGE,))


def engine_offenders(modules: dict[str, set[str]]) -> dict[str, list[str]]:
    outside_engines = {m: i for m, i in modules.items() if not m.startswith(ENGINES_PACKAGE)}
    return offenders(outside_engines, ENGINE_MODULES)


def voice_adapter_offenders(modules: dict[str, set[str]]) -> dict[str, list[str]]:
    adapters = {m: i for m, i in modules.items() if m in VOICE_ADAPTERS}
    return offenders(adapters, (ENGINES_PACKAGE, *ENGINE_MODULES))


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


def test_only_the_config_watcher_imports_watchfiles() -> None:
    assert users_of(core_modules(), "watchfiles") == WATCHFILES_ALLOWED_IN


def test_new_core_packages_import_neither_channels_nor_test_or_cli_frameworks() -> None:
    assert framework_free_offenders(core_modules()) == {}


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
    assert framework_free_offenders(
        {
            "tony.core.skills.index": {"pytest", "unicodedata"},
            "tony.core.doctor.checks": {"typer"},
            "tony.core.evals.replay": {"tony.core.channels.session"},
            "tony.core.runner.prompt": {"typer"},
        }
    ) == {
        "tony.core.skills.index": ["pytest"],
        "tony.core.doctor.checks": ["typer"],
        "tony.core.evals.replay": ["tony.core.channels.session"],
    }
    assert users_of({"tony.core.x": {"watchfiles"}}, "watchfiles") == {"tony.core.x"}


def test_web_frameworks_are_imported_only_by_the_web_app() -> None:
    assert web_framework_offenders({**core_modules(), **apps_modules()}) == {}


def test_the_web_app_never_imports_the_cli_app() -> None:
    assert web_to_cli_offenders(apps_modules()) == {}


def test_a_simulated_web_framework_leak_is_reported() -> None:
    simulated = {
        "tony.apps.web.server": {"fastapi", "starlette.staticfiles", "uvicorn"},
        "tony.apps.cli.main": {"typer", "uvicorn"},
        "tony.core.channels.bootstrap": {"starlette.requests"},
        "tony.apps.web.api": {"tony.apps.cli.render", "tony.core.memory"},
    }

    assert web_framework_offenders(simulated) == {
        "tony.apps.cli.main": ["uvicorn"],
        "tony.core.channels.bootstrap": ["starlette.requests"],
    }
    assert web_to_cli_offenders(simulated) == {"tony.apps.web.api": ["tony.apps.cli.render"]}


def test_voice_engines_are_imported_only_by_the_engines_package() -> None:
    assert engine_offenders({**core_modules(), **apps_modules()}) == {}


def test_voice_web_adapters_never_import_engines() -> None:
    assert voice_adapter_offenders(apps_modules()) == {}


def test_a_simulated_engine_leak_is_reported() -> None:
    simulated = {
        "tony.core.voice.engines.kokoro": {"kokoro", "torch", "asyncio"},
        "tony.core.voice.pipeline": {"asyncio", "onnxruntime"},
        "tony.apps.web.audio_ws": {"tony.core.voice.engines", "faster_whisper"},
        "tony.apps.web.tts_stream": {"tony.core.voice.pipeline"},
        "tony.apps.cli.voice_cli": {"typer"},
        "tony.core.voice.utterances": {"tony.core.channels.ports"},
    }

    assert engine_offenders(simulated) == {
        "tony.core.voice.pipeline": ["onnxruntime"],
        "tony.apps.web.audio_ws": ["faster_whisper"],
    }
    assert voice_adapter_offenders(simulated) == {
        "tony.apps.web.audio_ws": ["faster_whisper", "tony.core.voice.engines"]
    }
    assert framework_free_offenders(simulated) == {
        "tony.core.voice.utterances": ["tony.core.channels.ports"]
    }
