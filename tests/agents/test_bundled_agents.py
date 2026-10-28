"""The agents shipped in agents/ load and declare the expected policies."""

from __future__ import annotations

from pathlib import Path

from mcp.types import Tool

from tony.apps.cli.chat import load_roles
from tony.core.config import load_settings
from tony.core.loader import AgentSpec, StdioServer, load_agent, load_all
from tony.core.mcp import ToolCatalog

AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
FILESYSTEM_TOOLS = [
    "read_file",
    "read_text_file",
    "list_directory",
    "write_file",
    "edit_file",
    "move_file",
]


def simulated_catalog(confirm: list[str]) -> ToolCatalog:
    tools = {
        "filesystem": [
            Tool(name=name, description=name, inputSchema={"type": "object"})
            for name in FILESYSTEM_TOOLS
        ]
    }
    return ToolCatalog.build(tools, allow=None, confirm=confirm)


def test_viernes_is_a_worker_with_filesystem_mcp() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.role == "worker"
    assert spec.model == "claude-sonnet"
    assert "TaskResult" in spec.system_prompt
    assert isinstance(spec.tools.mcpServers["filesystem"], StdioServer)
    assert spec.tools.mcpServers["filesystem"].args[-1] == "/home/x/notas"
    assert spec.tools.allow is None


def test_viernes_marks_writes_as_needs_confirm() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    catalog = simulated_catalog(spec.tools.confirm)

    assert {ref.name for ref in catalog if ref.needs_confirm} == {
        "write_file",
        "edit_file",
        "move_file",
    }
    assert catalog.get("filesystem.read_file").needs_confirm is False


def test_load_all_returns_jarvis_and_viernes_without_errors() -> None:
    loaded = load_all(AGENTS_DIR, load_settings(None), {"HOME": "/home/x"})

    assert set(loaded) == {"jarvis", "viernes"}
    assert all(isinstance(spec, AgentSpec) for spec in loaded.values())
    assert loaded["jarvis"].role == "front"
    assert loaded["jarvis"].tools.native == ["delegate", "remember", "set_reply_mode"]
    assert loaded["jarvis"].tools.mcpServers == {}


def test_jarvis_prompt_explains_delegation_and_its_native_tools() -> None:
    spec = load_agent(AGENTS_DIR / "jarvis", load_settings(None), {})

    assert spec.role == "front"
    assert spec.model == "claude-haiku"
    for name in ("delegate", "remember", "set_reply_mode"):
        assert name in spec.system_prompt
    assert "display_text" in spec.system_prompt and "speech_text" in spec.system_prompt
    assert "ficheros" in spec.system_prompt


def test_swapped_roles_only_warn(tmp_path: Path) -> None:
    config = tmp_path / "tony.yaml"
    config.write_text("front: viernes\nworker: jarvis\n", encoding="utf-8")

    front, worker, warnings = load_roles(load_settings(config), AGENTS_DIR, {"HOME": "/home/x"})

    assert (front.name, worker.name) == ("viernes", "jarvis")
    assert warnings == [
        "Aviso: el agente 'viernes' tiene role 'worker' pero se usa como 'front'",
        "Aviso: el agente 'jarvis' tiene role 'front' pero se usa como 'worker'",
    ]


def test_viernes_ships_the_resumen_web_skill_with_its_triggers() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.skill_errors == []
    skill = next(s for s in spec.skills if s.name == "resumen-web")
    assert skill.description == "Resume una página web en 5 viñetas con fuente y fecha."
    assert skill.triggers == ["resume esta web", "resúmeme la página", "resume https"]
    assert "fetch.fetch" in skill.body
    assert spec.tools.native == ["read_skill", "run_subagent"]


def test_viernes_ships_the_investigador_subagent_without_tools_of_its_own() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.subagent_errors == {}
    child = spec.subagents["investigador"]
    assert child.role == "worker" and child.model == "claude-sonnet"
    assert child.tools.mcpServers == {} and child.tools.native == []
    assert child.parent == "viernes"
    assert "fuentes" in child.system_prompt
