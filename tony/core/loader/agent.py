from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.loader.agent_md import AgentSpec, parse_agent
from tony.core.loader.tool_json import ToolSpec, load_tool_spec

GUARD_ROLE = "guard"


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    spec: AgentSpec
    tools: ToolSpec


def load_agent(
    root: Path, name: str, config: TonyConfig, *, native_tools: Collection[str]
) -> AgentDefinition:
    folder = f"agents/{name}/"
    if not (root / folder).is_dir():
        raise DefinitionError(folder, None, f"agent folder {folder} does not exist")
    agent_file = f"{folder}agent.md"
    if not (root / agent_file).is_file():
        raise DefinitionError(agent_file, None, f"missing file {agent_file}")
    spec = parse_agent(
        (root / agent_file).read_text(), folder=name, file=agent_file, models=config.models
    )
    if spec.role == GUARD_ROLE:
        tools = _guard_tools(root, folder)
    else:
        tools = load_tool_spec(root, name, native_tools=native_tools)
    return AgentDefinition(name=name, spec=spec, tools=tools)


def _guard_tools(root: Path, folder: str) -> ToolSpec:
    tool_folder = f"{folder}tool/"
    if (root / tool_folder).exists():
        raise DefinitionError(
            tool_folder, None, f"a guard agent has no tools: remove {tool_folder}"
        )
    return ToolSpec(mcp_servers={})
