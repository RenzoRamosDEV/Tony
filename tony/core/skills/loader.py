"""Load skills from agents/<agent>/skills/<name>/SKILL.md."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from tony.core.loader.errors import format_validation_error
from tony.core.loader.frontmatter import FrontmatterError, split_frontmatter
from tony.core.skills.models import SkillLoadError, SkillSpec

SKILL_FILE = "SKILL.md"


def parse_skill(skill_md: Path) -> SkillSpec:
    """Parse one SKILL.md; its `name` must equal the folder that contains it."""
    folder = skill_md.parent
    skill = folder.name
    if not skill_md.is_file():
        raise SkillLoadError(skill, f"no existe {skill_md.name}")
    try:
        header, body = split_frontmatter(skill_md.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise SkillLoadError(skill, str(exc)) from None
    name = header.get("name")
    if name != skill:
        raise SkillLoadError(skill, f"name '{name}' no coincide con la carpeta '{skill}'")
    try:
        return SkillSpec.model_validate(
            {
                "name": name,
                "description": header.get("description"),
                "triggers": header.get("trigger", []),
                "body": body,
                "path": folder,
            }
        )
    except ValidationError as exc:
        raise SkillLoadError(skill, format_validation_error(exc)) from None


def load_skills(skills_dir: Path) -> tuple[list[SkillSpec], list[SkillLoadError]]:
    """Every skill folder under skills_dir; broken ones are reported, not raised."""
    skills: list[SkillSpec] = []
    errors: list[SkillLoadError] = []
    if not skills_dir.is_dir():
        return skills, errors
    for folder in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        try:
            skills.append(parse_skill(folder / SKILL_FILE))
        except SkillLoadError as exc:
            errors.append(exc)
    return skills, errors
