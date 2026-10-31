"""The agents shipped in agents/ load and declare the expected policies."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from mcp.types import Tool

from tony.apps.cli.chat import load_roles
from tony.core.config import load_settings
from tony.core.loader import AgentSpec, StdioServer, load_agent, load_all
from tony.core.mcp import ToolCatalog

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ALLOWED_TOP_LEVEL_NAMES = {"agent.md", "tool", "skills", "subagents"}
_ALLOWED_NESTED_NAMES = {"agent.md", "tool", "skills"}


def _agent_folder_convention_violations(agents_dir: Path) -> list[str]:
    """Return a human-readable violation per broken rule, or an empty list."""
    violations: list[str] = []

    def check_agent_folder(folder: Path, *, allow_subagents: bool) -> None:
        if not _KEBAB_CASE.match(folder.name):
            violations.append(f"{folder}: el nombre de carpeta no es kebab-case en minúsculas")

        allowed = _ALLOWED_TOP_LEVEL_NAMES if allow_subagents else _ALLOWED_NESTED_NAMES
        for entry in folder.iterdir():
            if entry.name not in allowed:
                violations.append(f"{entry}: archivo o carpeta no permitido dentro de la convención")

        tool_dir = folder / "tool"
        if tool_dir.is_dir():
            extra = [p.name for p in tool_dir.iterdir() if p.name != "tool.json"]
            for name in extra:
                violations.append(f"{tool_dir / name}: solo se permite tool.json dentro de tool/")

        skills_dir = folder / "skills"
        if skills_dir.is_dir():
            for skill_dir in skills_dir.iterdir():
                if not _KEBAB_CASE.match(skill_dir.name):
                    violations.append(f"{skill_dir}: el nombre de skill no es kebab-case en minúsculas")

        subagents_dir = folder / "subagents"
        if subagents_dir.is_dir():
            if not allow_subagents:
                violations.append(f"{subagents_dir}: subagents/ anidado dentro de otro subagents/")
            else:
                for child in subagents_dir.iterdir():
                    check_agent_folder(child, allow_subagents=False)

    for agent_folder in agents_dir.iterdir():
        if agent_folder.is_dir():
            check_agent_folder(agent_folder, allow_subagents=True)

    return violations

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
    assert spec.model == "claude-haiku"
    assert spec.effort == "medium"
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
    assert spec.effort == "medium"
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
    assert child.role == "worker" and child.model == "claude-haiku"
    assert child.effort == "medium"
    assert child.tools.mcpServers == {} and child.tools.native == []
    assert child.parent == "viernes"
    assert "fuentes" in child.system_prompt


def test_viernes_prompt_tells_it_about_its_subagents() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert "calendario" in spec.system_prompt and "archivista" in spec.system_prompt
    assert "run_subagent" in spec.system_prompt


def test_viernes_ships_the_calendario_skill_with_its_triggers() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.skill_errors == []
    skill = next(s for s in spec.skills if s.name == "calendario")
    assert "Google Calendar" in skill.description
    assert "calendario" in skill.triggers
    assert "cuenta" in skill.body


def test_viernes_ships_the_notas_skill_with_its_triggers() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.skill_errors == []
    skill = next(s for s in spec.skills if s.name == "notas")
    assert "apunta esto" in skill.triggers
    assert "write_file" in skill.body


def test_viernes_ships_the_calendario_subagent_with_only_google_calendar_mcp() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.subagent_errors == {}
    child = spec.subagents["calendario"]
    assert child.role == "worker" and child.model == "claude-haiku"
    assert child.effort == "medium"
    assert set(child.tools.mcpServers) == {"google-calendar"}
    assert child.tools.native == []
    assert child.parent == "viernes"
    assert child.tools.confirm == [
        "google-calendar.create-event",
        "google-calendar.update-event",
        "google-calendar.delete-event",
    ]


def test_viernes_ships_the_archivista_subagent_with_only_filesystem_mcp() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.subagent_errors == {}
    child = spec.subagents["archivista"]
    assert child.role == "worker" and child.model == "claude-haiku"
    assert child.effort == "medium"
    assert isinstance(child.tools.mcpServers["filesystem"], StdioServer)
    assert child.tools.mcpServers["filesystem"].args[-1] == "/home/x/notas"
    assert child.tools.native == []
    assert child.parent == "viernes"
    assert child.tools.confirm == [
        "filesystem.write_file",
        "filesystem.edit_file",
        "filesystem.move_file",
    ]


def test_jarvis_speaks_in_a_serene_neutral_latin_american_style() -> None:
    from datetime import datetime

    from tony.core.runner.front_prompt import build_turn_preamble
    from tony.core.runner.reply_mode import EffectiveMode

    spec = load_agent(AGENTS_DIR / "jarvis", load_settings(None), {})
    preamble = build_turn_preamble(
        datetime(2026, 10, 28, 12, 0).astimezone(), EffectiveMode("voice", "prefix"), spec.style, ""
    )

    voice = spec.style.voice or ""
    for fragment in ("señor", "sereno", "español latinoamericano neutro"):
        assert fragment in voice
    assert f"Estilo: {voice}" in preamble
    assert spec.system_prompt.index("speech_text") < spec.system_prompt.index("display_text")


def test_bundled_agents_follow_the_folder_convention() -> None:
    assert _agent_folder_convention_violations(AGENTS_DIR) == []


def test_folder_convention_rejects_a_non_kebab_case_agent_name(tmp_path: Path) -> None:
    shutil.copytree(AGENTS_DIR, tmp_path / "agents")
    shutil.move(str(tmp_path / "agents" / "viernes"), str(tmp_path / "agents" / "Viernes_v2"))

    violations = _agent_folder_convention_violations(tmp_path / "agents")

    assert any("Viernes_v2" in v and "kebab-case" in v for v in violations)


def test_folder_convention_rejects_a_stray_file_in_an_agent_folder(tmp_path: Path) -> None:
    shutil.copytree(AGENTS_DIR, tmp_path / "agents")
    (tmp_path / "agents" / "jarvis" / "notes.txt").write_text("stray", encoding="utf-8")

    violations = _agent_folder_convention_violations(tmp_path / "agents")

    assert any("notes.txt" in v for v in violations)


def test_folder_convention_rejects_a_subagent_nesting_its_own_subagents(tmp_path: Path) -> None:
    shutil.copytree(AGENTS_DIR, tmp_path / "agents")
    nested = tmp_path / "agents" / "viernes" / "subagents" / "investigador" / "subagents" / "ghost"
    nested.mkdir(parents=True)
    (nested / "agent.md").write_text("---\nrole: worker\nmodel: claude-sonnet\n---\nHola\n", encoding="utf-8")

    violations = _agent_folder_convention_violations(tmp_path / "agents")

    assert any("subagents/ anidado" in v for v in violations)


def test_folder_convention_has_no_false_positive_for_an_agent_without_skills_or_subagents() -> None:
    violations = _agent_folder_convention_violations(AGENTS_DIR)

    assert not any("jarvis" in v for v in violations)


def test_folder_convention_has_no_false_positive_for_a_subagent_without_tool() -> None:
    violations = _agent_folder_convention_violations(AGENTS_DIR)

    assert not any("investigador" in v for v in violations)
