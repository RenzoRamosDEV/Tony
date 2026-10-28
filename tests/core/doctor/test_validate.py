"""validate_agent: the exact results the reloader and doctor rely on."""

from __future__ import annotations

from pathlib import Path

from tests.apps.cli_helpers import write_agent
from tony.core.config import load_settings
from tony.core.doctor.validate import CheckResult, validate_agent

SETTINGS = load_settings(None)


def write_skill(agent: Path, name: str, frontmatter: str) -> None:
    path = agent / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{frontmatter}---\ncuerpo\n", encoding="utf-8")


def test_valid_agent_with_skill_and_subagent(tmp_path: Path) -> None:
    write_agent(tmp_path, "viernes", "worker")
    write_skill(tmp_path / "viernes", "s", "name: s\ndescription: d\n")
    write_agent(tmp_path / "viernes" / "subagents", "investigador", "worker", model="claude-haiku")
    write_skill(
        tmp_path / "viernes" / "subagents" / "investigador", "t", "name: t\ndescription: e\n"
    )

    assert validate_agent(tmp_path, "viernes", SETTINGS, {}) == [
        CheckResult("agente viernes", True, "worker, claude-sonnet"),
        CheckResult("skill viernes/s", True, "d"),
        CheckResult("subagente viernes/investigador", True, "claude-haiku"),
        CheckResult("skill viernes/subagents/investigador/t", True, "e"),
    ]


def test_broken_agent_is_a_single_failure(tmp_path: Path) -> None:
    write_agent(tmp_path, "roto", "helper")

    results = validate_agent(tmp_path, "roto", SETTINGS, {})

    assert len(results) == 1
    assert results[0].name == "agente roto" and results[0].ok is False
    assert "role" in results[0].detail
    assert results[0].hint == (
        "revisa agents/roto/agent.md y tool/tool.json; define toda variable ${VAR} en config/.env"
    )


def test_skill_and_subagent_errors_are_failures_with_hints(tmp_path: Path) -> None:
    write_agent(tmp_path, "viernes", "worker")
    write_skill(tmp_path / "viernes", "mala", "name: mala\n")
    write_agent(tmp_path / "viernes" / "subagents", "roto", "helper")

    results = validate_agent(tmp_path, "viernes", SETTINGS, {})

    assert results[0] == CheckResult("agente viernes", True, "worker, claude-sonnet")
    skill = results[1]
    assert skill.name == "skill viernes/mala" and skill.ok is False
    assert skill.detail.startswith("description: ")
    assert skill.hint == "revisa el frontmatter de agents/viernes/skills/mala/SKILL.md"
    child = results[2]
    assert child.name == "subagente viernes/roto" and child.ok is False and "role" in child.detail
    assert child.hint == "revisa agents/viernes/subagents/roto/"
    assert len(results) == 3


def test_check_result_failed_only_for_false() -> None:
    assert CheckResult("a", False).failed is True
    assert CheckResult("a", True).failed is False
    assert CheckResult("a", None).failed is False
