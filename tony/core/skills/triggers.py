"""Automatic skill activation: trigger phrases matched without case or accents."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from tony.core.skills.models import SkillSpec


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def matched_skills(text: str, skills: Sequence[SkillSpec]) -> list[SkillSpec]:
    haystack = normalize(text)
    return [
        skill
        for skill in skills
        if any(normalize(phrase) in haystack for phrase in skill.triggers if phrase)
    ]


def skill_blocks(text: str, skills: Sequence[SkillSpec]) -> str:
    return "".join(
        f'<skill name="{skill.name}">\n{skill.body}\n</skill>\n\n'
        for skill in matched_skills(text, skills)
    )
