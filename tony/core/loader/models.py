"""Agent definition models: agent.md frontmatter and tool/tool.json."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from tony.core.skills.models import SkillSpec

NATIVE_TOOLS: tuple[str, ...] = (
    "delegate",
    "remember",
    "set_reply_mode",
    "read_skill",
    "run_subagent",
)

MAX_STEPS_RANGE = (1, 200)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Persona(StrictModel):
    address: str = ""
    language: str = "es"


class Style(StrictModel):
    voice: str = ""
    text: str = ""


class StdioServer(StrictModel):
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class HttpServer(StrictModel):
    url: str
    headers: dict[str, str] = {}


class ToolConfig(StrictModel):
    mcpServers: dict[str, StdioServer | HttpServer] = {}
    native: list[str] = []
    allow: list[str] | None = None
    confirm: list[str] = []

    @field_validator("mcpServers", mode="before")
    @classmethod
    def each_server_has_exactly_one_transport(cls, servers: Any) -> dict[str, Any]:
        if not isinstance(servers, dict):
            raise ValueError("mcpServers debe ser un objeto")
        for name, server in servers.items():
            if isinstance(server, StdioServer | HttpServer):
                continue
            if not isinstance(server, dict):
                raise ValueError(f"servidor {name}: debe ser un objeto")
            has_command, has_url = "command" in server, "url" in server
            if has_command == has_url:
                raise ValueError(
                    f"servidor {name}: debe tener exactamente uno de "
                    "'command' (stdio) o 'url' (HTTP)"
                )
        return servers

    @field_validator("native")
    @classmethod
    def native_tools_in_catalog(cls, names: list[str]) -> list[str]:
        unknown = [name for name in names if name not in NATIVE_TOOLS]
        if unknown:
            raise ValueError(
                f"tools nativas desconocidas {unknown}; catálogo permitido: {list(NATIVE_TOOLS)}"
            )
        return names


class AgentSpec(StrictModel):
    name: str
    role: Literal["front", "worker"]
    model: str
    persona: Persona = Persona()
    style: Style = Style()
    max_steps: int = 20
    wait_phrase: str = "Dame un momento."
    system_prompt: str = ""
    path: Path
    tools: ToolConfig = ToolConfig()
    secrets: list[str] = []
    """Values substituted from the environment into tools; redacted from logs."""
    skills: list[SkillSpec] = []
    skill_errors: list[str] = []
    subagents: dict[str, AgentSpec] = {}
    subagent_errors: dict[str, str] = {}
    parent: str | None = None

    @field_validator("max_steps")
    @classmethod
    def max_steps_in_range(cls, value: int) -> int:
        low, high = MAX_STEPS_RANGE
        if not low <= value <= high:
            raise ValueError(f"debe estar en el rango {low}..{high}")
        return value

    @model_validator(mode="after")
    def name_is_not_blank(self) -> AgentSpec:
        if not self.name.strip():
            raise ValueError("name no puede estar vacío")
        return self
