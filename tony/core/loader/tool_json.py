import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tony.core.config.errors import DefinitionError

RESERVED_SERVER = "tony"
SERVER_NAME = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
PERMISSION_KEYS = {"allow", "confirm"}
POLICY_FILE = "agents/edith/policy.yaml"
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


def agent_folder(key: str) -> str:
    parts = key.split("/")
    if len(parts) > 2 or any(part in {"", ".", ".."} for part in parts):
        raise DefinitionError(key, None, f"invalid agent key '{key}'")
    if len(parts) == 1:
        return f"agents/{key}/"
    return f"agents/{parts[0]}/subagents/{parts[1]}/"


def tool_file(key: str) -> str:
    return f"{agent_folder(key)}tool/tool.json"


def tool_json_keys(root: Path) -> list[str]:
    """Keys of every agent and subagent folder that has a `tool.json`, parents first."""
    agents = [path.parents[1].name for path in root.glob("agents/*/tool/tool.json")]
    subagents = [
        f"{path.parents[3].name}/{path.parents[1].name}"
        for path in root.glob("agents/*/subagents/*/tool/tool.json")
    ]
    return sorted([*agents, *subagents])


def load_tool_spec(root: Path, key: str, *, native_tools: Collection[str]) -> ToolSpec:
    file = tool_file(key)
    path = root / file
    if not path.is_file():
        raise DefinitionError(file, None, f"missing file {file}")
    return parse_tool_spec(path.read_text(), file=file, native_tools=native_tools)


def parse_tool_spec(text: str, *, file: str, native_tools: Collection[str]) -> ToolSpec:
    data = _parse_json(text, file)
    forbidden = _find_permission_key(data)
    if forbidden:
        raise DefinitionError(file, forbidden, f"permissions belong to {POLICY_FILE}")
    try:
        spec = ToolSpec.model_validate(data)
    except ValidationError as error:
        raise DefinitionError.from_validation(file, error) from error
    for name in spec.mcp_servers:
        _check_server_name(name, file)
    unknown = [name for name in spec.native if name not in native_tools]
    if unknown:
        raise DefinitionError(file, "native", f"unknown native tools {unknown}")
    return spec


def _check_server_name(name: str, file: str) -> None:
    if name == RESERVED_SERVER:
        raise DefinitionError(file, f"mcpServers.{name}", "server name 'tony' is reserved")
    if not SERVER_NAME.fullmatch(name):
        raise DefinitionError(
            file,
            f"mcpServers.{name}",
            "server name must be letters or digits separated by single '-' or '_'",
        )


def _parse_json(text: str, file: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise DefinitionError(file, None, f"invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise DefinitionError(file, None, "must be a JSON object")
    return data


def _find_permission_key(node: Any, path: str = "") -> str | None:
    if isinstance(node, dict):
        children = node.items()
    elif isinstance(node, list):
        children = ((str(index), item) for index, item in enumerate(node))
    else:
        return None
    for key, child in children:
        child_path = f"{path}.{key}" if path else key
        if isinstance(node, dict) and key in PERMISSION_KEYS:
            return child_path
        found = _find_permission_key(child, child_path)
        if found:
            return found
    return None
