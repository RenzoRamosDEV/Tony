"""Skills and subagents inside the agent folder (specs/agent-loader)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tony.core.config import load_settings
from tony.core.loader import AgentSpec, ToolConfig, load_agent, load_all

SETTINGS = load_settings(None)


def write_agent(folder: Path, name: str, role: str = "worker", model: str = "claude-sonnet"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "agent.md").write_text(
        f"---\nname: {name}\nrole: {role}\nmodel: {model}\n---\nEres {name}.\n", encoding="utf-8"
    )
    return folder


def write_skill(agent: Path, name: str, frontmatter: str) -> None:
    path = agent / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{frontmatter}---\ncuerpo de {name}\n", encoding="utf-8")


def write_tool_json(agent: Path, data: dict) -> None:
    (agent / "tool").mkdir(exist_ok=True)
    (agent / "tool" / "tool.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def viernes(tmp_path: Path) -> Path:
    return write_agent(tmp_path / "viernes", "viernes")


def test_agent_loads_valid_skills_and_reports_broken_ones(viernes: Path) -> None:
    write_skill(viernes, "resumen-web", "name: resumen-web\ndescription: Resume\n")
    write_skill(viernes, "mala", "name: mala\n")

    spec = load_agent(viernes, SETTINGS, {})

    assert [s.name for s in spec.skills] == ["resumen-web"]
    assert spec.skills[0].body == "cuerpo de resumen-web"
    assert len(spec.skill_errors) == 1
    assert spec.skill_errors[0].startswith("mala: ") and "description" in spec.skill_errors[0]


def test_agent_without_skills_folder_has_none(viernes: Path) -> None:
    spec = load_agent(viernes, SETTINGS, {})

    assert spec.skills == [] and spec.skill_errors == []


def test_valid_subagent_without_tool_json_inherits_nothing_and_knows_its_parent(
    viernes: Path,
) -> None:
    write_agent(viernes / "subagents" / "investigador", "investigador")

    spec = load_agent(viernes, SETTINGS, {})

    child = spec.subagents["investigador"]
    assert isinstance(child, AgentSpec)
    assert child.tools == ToolConfig()
    assert child.parent == "viernes"
    assert child.path == viernes / "subagents" / "investigador"
    assert spec.parent is None
    assert spec.subagent_errors == {}


def test_subagent_loads_its_own_skills_and_tool_json(viernes: Path) -> None:
    child = write_agent(viernes / "subagents" / "investigador", "investigador")
    write_skill(child, "fuentes", "name: fuentes\ndescription: Busca fuentes\n")
    write_tool_json(child, {"native": ["read_skill"], "allow": ["fs.read_file"]})

    spec = load_agent(viernes, SETTINGS, {})

    loaded = spec.subagents["investigador"]
    assert [s.name for s in loaded.skills] == ["fuentes"]
    assert loaded.tools.native == ["read_skill"]
    assert loaded.tools.allow == ["fs.read_file"]


def test_broken_subagent_is_reported_without_failing_the_parent(viernes: Path) -> None:
    write_agent(viernes / "subagents" / "roto", "roto", role="helper")
    write_agent(viernes / "subagents" / "investigador", "investigador")

    spec = load_agent(viernes, SETTINGS, {})

    assert set(spec.subagents) == {"investigador"}
    assert "role" in spec.subagent_errors["roto"]


def test_subagent_with_front_role_loads_with_a_warning(
    viernes: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_agent(viernes / "subagents" / "x", "x", role="front")

    with caplog.at_level(logging.WARNING):
        spec = load_agent(viernes, SETTINGS, {})

    assert spec.subagents["x"].role == "front"
    warning = next(r.message for r in caplog.records if "'x'" in r.message)
    assert "front" in warning and "worker" in warning


def test_nested_subagents_are_ignored(viernes: Path) -> None:
    write_agent(viernes / "subagents" / "investigador", "investigador")
    write_agent(viernes / "subagents" / "investigador" / "subagents" / "otro", "otro")

    spec = load_agent(viernes, SETTINGS, {})

    assert spec.subagents["investigador"].subagents == {}
    assert spec.subagents["investigador"].subagent_errors == {}


def test_run_subagent_is_removed_from_a_subagent_with_a_warning(
    viernes: Path, caplog: pytest.LogCaptureFixture
) -> None:
    child = write_agent(viernes / "subagents" / "investigador", "investigador")
    write_tool_json(child, {"native": ["run_subagent", "read_skill"]})

    with caplog.at_level(logging.WARNING):
        spec = load_agent(viernes, SETTINGS, {})

    assert spec.subagents["investigador"].tools.native == ["read_skill"]
    assert any("run_subagent" in r.message and "investigador" in r.message for r in caplog.records)


def test_load_all_includes_subagents_and_their_errors(tmp_path: Path) -> None:
    viernes = write_agent(tmp_path / "viernes", "viernes")
    write_agent(viernes / "subagents" / "investigador", "investigador")
    write_agent(tmp_path / "jarvis", "jarvis", role="front", model="claude-haiku")

    loaded = load_all(tmp_path, SETTINGS, {})

    assert set(loaded["viernes"].subagents) == {"investigador"}
    assert loaded["jarvis"].subagents == {}
    assert loaded["jarvis"].subagent_errors == {}


def test_subagents_folder_with_a_loose_file_is_ignored(viernes: Path) -> None:
    (viernes / "subagents").mkdir()
    (viernes / "subagents" / "notas.txt").write_text("x", encoding="utf-8")

    assert load_agent(viernes, SETTINGS, {}).subagents == {}


def test_all_secrets_collects_the_subagent_secrets_without_duplicates(viernes: Path) -> None:
    write_tool_json(viernes, {"mcpServers": {"a": {"url": "https://a", "headers": {"X": "${T}"}}}})
    child = write_agent(viernes / "subagents" / "investigador", "investigador")
    write_tool_json(
        child,
        {"mcpServers": {"b": {"url": "https://b", "headers": {"X": "${T}", "Y": "${CHILD}"}}}},
    )

    spec = load_agent(viernes, SETTINGS, {"T": "token-largo-1", "CHILD": "clave-del-hijo"})

    assert spec.secrets == ["token-largo-1"]
    assert spec.all_secrets() == ["token-largo-1", "clave-del-hijo"]
