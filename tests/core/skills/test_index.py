"""Skills index for the system prompt and `read_skill` lookup (specs/agent-skills)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tony.core.skills import SkillSpec
from tony.core.skills.index import NO_SKILLS, UnknownSkill, find_skill, skills_index


def skill(name: str, description: str, body: str = "cuerpo secreto") -> SkillSpec:
    return SkillSpec(name=name, description=description, body=body, path=Path(f"/s/{name}"))


SKILLS = [skill("resumen-web", "Resume una página web"), skill("informe", "Redacta un informe")]


def test_index_lists_names_and_descriptions_without_bodies() -> None:
    index = skills_index(SKILLS)

    assert index == (
        "Skills disponibles:\n- resumen-web: Resume una página web\n- informe: Redacta un informe"
    )
    assert "cuerpo secreto" not in index


def test_index_without_skills_is_empty() -> None:
    assert skills_index([]) == ""


def test_find_skill_returns_the_named_skill() -> None:
    assert find_skill(SKILLS, "informe") is SKILLS[1]


def test_unknown_skill_lists_the_available_ones() -> None:
    with pytest.raises(UnknownSkill) as info:
        find_skill(SKILLS, "traducir")

    message = str(info.value)
    assert "traducir" in message and "resumen-web" in message and "informe" in message


def test_find_skill_without_skills_says_there_are_none() -> None:
    with pytest.raises(UnknownSkill, match=NO_SKILLS):
        find_skill([], "x")


def test_unknown_skill_message_is_exact() -> None:
    with pytest.raises(UnknownSkill) as info:
        find_skill(SKILLS, "traducir")

    assert str(info.value) == "skill 'traducir' desconocida; disponibles: resumen-web, informe"
