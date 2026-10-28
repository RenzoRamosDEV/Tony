"""Tests for tolerant loading of every agent in a directory (specs/agent-loader)."""

from __future__ import annotations

from pathlib import Path

from tony.core.config import load_settings
from tony.core.loader import AgentLoadError, AgentSpec, load_all


def write_agent(agents_dir: Path, name: str, role: str) -> None:
    folder = agents_dir / name
    folder.mkdir(parents=True)
    (folder / "agent.md").write_text(
        f"---\nname: {name}\nrole: {role}\nmodel: claude-sonnet\n---\nHola\n", encoding="utf-8"
    )


def test_one_broken_agent_does_not_block_the_others(tmp_repo: Path) -> None:
    agents_dir = tmp_repo / "agents"
    write_agent(agents_dir, "viernes", "worker")
    write_agent(agents_dir, "roto", "helper")

    result = load_all(agents_dir, load_settings(None), {})

    assert set(result) == {"viernes", "roto"}
    assert isinstance(result["viernes"], AgentSpec)
    assert result["viernes"].name == "viernes"
    assert isinstance(result["roto"], AgentLoadError)
    assert "role" in str(result["roto"])


def test_empty_directory_yields_empty_map(tmp_repo: Path) -> None:
    assert load_all(tmp_repo / "agents", load_settings(None), {}) == {}


def test_plain_files_in_agents_dir_are_ignored(tmp_repo: Path) -> None:
    (tmp_repo / "agents" / "README.md").write_text("x", encoding="utf-8")

    assert load_all(tmp_repo / "agents", load_settings(None), {}) == {}


def test_malformed_agents_are_reported_without_breaking_the_rest(tmp_repo: Path) -> None:
    agents_dir = tmp_repo / "agents"
    write_agent(agents_dir, "viernes", "worker")
    write_agent(agents_dir, "lista", "worker")
    (agents_dir / "lista" / "tool").mkdir()
    (agents_dir / "lista" / "tool" / "tool.json").write_text("[]", encoding="utf-8")
    (agents_dir / "yaml").mkdir()
    (agents_dir / "yaml" / "agent.md").write_text("---\nname: [\n---\nHola\n", encoding="utf-8")
    (agents_dir / "reservado").mkdir()
    (agents_dir / "reservado" / "agent.md").write_text(
        "---\nname: r\nrole: worker\nmodel: claude-sonnet\npath: /x\n---\nHola\n", encoding="utf-8"
    )

    result = load_all(agents_dir, load_settings(None), {})

    assert isinstance(result["viernes"], AgentSpec)
    assert {name for name, item in result.items() if isinstance(item, AgentLoadError)} == {
        "lista",
        "yaml",
        "reservado",
    }
