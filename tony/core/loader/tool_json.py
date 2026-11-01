import json
from collections.abc import Collection
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tony.core.config.errors import DefinitionError

RESERVED_SERVER = "tony"
_STDIO_ONLY = {"args", "env"}
_HTTP_ONLY = {"headers"}


class McpServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}

    @model_validator(mode="after")
    def _one_transport(self) -> "McpServer":
        if (self.command is None) == (self.url is None):
            raise ValueError("define exactly one of 'command' or 'url'")
        foreign = _HTTP_ONLY if self.is_stdio else _STDIO_ONLY
        misplaced = sorted(foreign & self.model_fields_set)
        if misplaced:
            raise ValueError(f"keys {misplaced} do not apply to this transport")
        return self

    @property
    def is_stdio(self) -> bool:
        return self.command is not None


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mcp_servers: dict[str, McpServer] = Field(alias="mcpServers")
    native: list[str] = []


def tool_file(agent: str) -> str:
    return f"agents/{agent}/tool/tool.json"


def load_tool_spec(root: Path, agent: str, *, native_tools: Collection[str]) -> ToolSpec:
    file = tool_file(agent)
    path = root / file
    if not path.is_file():
        raise DefinitionError(file, None, f"missing file {file}")
    return parse_tool_spec(path.read_text(), file=file, native_tools=native_tools)


def parse_tool_spec(text: str, *, file: str, native_tools: Collection[str]) -> ToolSpec:
    data = _parse_json(text, file)
    try:
        spec = ToolSpec.model_validate(data)
    except ValidationError as error:
        raise DefinitionError.from_validation(file, error) from error
    if RESERVED_SERVER in spec.mcp_servers:
        raise DefinitionError(
            file, f"mcpServers.{RESERVED_SERVER}", "server name 'tony' is reserved"
        )
    unknown = [name for name in spec.native if name not in native_tools]
    if unknown:
        raise DefinitionError(file, "native", f"unknown native tools {unknown}")
    return spec


def _parse_json(text: str, file: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise DefinitionError(file, None, f"invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise DefinitionError(file, None, "must be a JSON object")
    return data
