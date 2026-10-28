"""What the model sees about skills: the index, and the lookup behind `read_skill`."""

from __future__ import annotations

from collections.abc import Sequence

from tony.core.skills.models import SkillSpec

INDEX_HEADER = "Skills disponibles:"
NO_SKILLS = "no hay skills disponibles"


class UnknownSkill(ValueError):
    pass


def skills_index(skills: Sequence[SkillSpec]) -> str:
    if not skills:
        return ""
    lines = [f"- {skill.name}: {skill.description}" for skill in skills]
    return "\n".join([INDEX_HEADER, *lines])


def find_skill(skills: Sequence[SkillSpec], name: str) -> SkillSpec:
    for skill in skills:
        if skill.name == name:
            return skill
    if not skills:
        raise UnknownSkill(NO_SKILLS)
    available = ", ".join(skill.name for skill in skills)
    raise UnknownSkill(f"skill '{name}' desconocida; disponibles: {available}")
