from collections.abc import Collection
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tony.core.config.errors import DefinitionError

DELIMITER = "---"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Persona(_Strict):
    language: str
    tone: str


class Voice(_Strict):
    tts: str = Field(pattern=r"^kokoro/\S+$")


class AgentFrontmatter(_Strict):
    name: str
    role: Literal["front", "worker", "guard"]
    model: str
    persona: Persona
    voice: Voice


class AgentSpec(AgentFrontmatter):
    system_prompt: str


def parse_agent(text: str, *, folder: str, file: str, models: Collection[str]) -> AgentSpec:
    raw, body = split_frontmatter(text, file)
    try:
        frontmatter = AgentFrontmatter.model_validate(raw)
    except ValidationError as error:
        raise DefinitionError.from_validation(file, error) from error
    if frontmatter.name != folder:
        raise DefinitionError(file, "name", f"must equal the agent folder name '{folder}'")
    if frontmatter.model not in models:
        raise DefinitionError(file, "model", f"model alias '{frontmatter.model}' is not configured")
    return AgentSpec(**frontmatter.model_dump(), system_prompt=body)


def split_frontmatter(text: str, file: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0] != DELIMITER or DELIMITER not in lines[1:]:
        raise DefinitionError(file, None, "missing '---' delimited YAML frontmatter")
    closing = lines.index(DELIMITER, 1)
    frontmatter = _parse_yaml("\n".join(lines[1:closing]), file)
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise DefinitionError(file, None, "system prompt body must not be empty")
    return frontmatter, body


def _parse_yaml(text: str, file: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise DefinitionError(file, None, f"invalid YAML frontmatter: {error}") from error
    if not isinstance(data, dict):
        raise DefinitionError(file, None, "frontmatter must be a YAML mapping")
    return data
