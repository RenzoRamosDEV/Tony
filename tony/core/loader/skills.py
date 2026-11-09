from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tony.core.config.errors import DefinitionError
from tony.core.loader.agent_md import split_frontmatter
from tony.core.loader.tool_json import agent_folder

SKILL_FILE = "SKILL.md"


class _SkillFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = Field(pattern=r"\S")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str


def list_skills(root: Path, key: str) -> tuple[list[Skill], list[DefinitionError]]:
    folder = f"{agent_folder(key)}skills/"
    if not (root / folder).is_dir():
        return [], []
    skills: list[Skill] = []
    errors: list[DefinitionError] = []
    for path in sorted((root / folder).iterdir()):
        if not (path / SKILL_FILE).is_file():
            continue
        try:
            skills.append(_parse_skill(path, f"{folder}{path.name}/{SKILL_FILE}"))
        except DefinitionError as error:
            errors.append(error)
    return sorted(skills, key=lambda skill: skill.name), errors


def read_skill_body(root: Path, key: str, name: str) -> str | None:
    if not _is_plain_folder_name(name):
        return None
    folder = f"{agent_folder(key)}skills/{name}"
    if not (root / folder / SKILL_FILE).is_file():
        return None
    try:
        return _parse_skill(root / folder, f"{folder}/{SKILL_FILE}").body
    except DefinitionError:
        return None


def _is_plain_folder_name(name: str) -> bool:
    return name not in ("", ".", "..") and Path(name).name == name


def _parse_skill(path: Path, file: str) -> Skill:
    raw, body = split_frontmatter((path / SKILL_FILE).read_text(), file)
    try:
        frontmatter = _SkillFrontmatter.model_validate(raw)
    except ValidationError as error:
        raise DefinitionError.from_validation(file, error) from error
    if frontmatter.name != path.name:
        raise DefinitionError(file, "name", f"must equal the skill folder name '{path.name}'")
    return Skill(frontmatter.name, frontmatter.description, body)
