"""Skill definition loaded from SKILL.md."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

MAX_DESCRIPTION = 200


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = Field(max_length=MAX_DESCRIPTION)
    triggers: list[str] = []
    body: str = ""
    path: Path


class SkillLoadError(Exception):
    """A skill folder could not be loaded; carries the skill name and the reason."""

    def __init__(self, skill: str, message: str) -> None:
        super().__init__(f"{skill}: {message}")
        self.skill = skill
        self.message = message
