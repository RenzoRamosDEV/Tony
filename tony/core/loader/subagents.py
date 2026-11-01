from collections.abc import Callable, Collection
from pathlib import Path

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.loader.agent import AgentDefinition, load_agent
from tony.core.loader.agent_md import AgentSpec, parse_agent
from tony.core.loader.tool_json import ToolSpec, agent_folder, tool_file

WORKER_ROLE = "worker"
RUN_SUBAGENT = "run_subagent"


def list_subagents(root: Path, parent: str, config: TonyConfig) -> list[tuple[str, str]]:
    listed = []
    for name in _subagent_names(root, parent):
        key = f"{parent}/{name}"
        try:
            spec = _parse_spec(root, key, config)
        except DefinitionError:
            continue
        listed.append((name, spec.description))
    return listed


def load_subagent(
    root: Path,
    parent: str,
    name: str,
    config: TonyConfig,
    *,
    native_tools: Collection[str],
    tools_for: Callable[[str], ToolSpec] | None = None,
) -> AgentDefinition | None:
    if name not in _subagent_names(root, parent):
        return None
    key = f"{parent}/{name}"
    tools = tools_for(key) if tools_for is not None else None
    agent = load_agent(root, key, config, native_tools=native_tools, tools=tools)
    _check_subagent(agent.spec, f"{agent_folder(key)}agent.md")
    if RUN_SUBAGENT in agent.tools.native:
        raise DefinitionError(tool_file(key), "native", "a subagent cannot run subagents")
    return agent


def _subagent_names(root: Path, parent: str) -> list[str]:
    folder = root / f"{agent_folder(parent)}subagents"
    if not folder.is_dir():
        return []
    return sorted(path.name for path in folder.iterdir() if (path / "agent.md").is_file())


def _parse_spec(root: Path, key: str, config: TonyConfig) -> AgentSpec:
    file = f"{agent_folder(key)}agent.md"
    spec = parse_agent(
        (root / file).read_text(),
        folder=key.rsplit("/", 1)[-1],
        file=file,
        models=config.models,
    )
    _check_subagent(spec, file)
    return spec


def _check_subagent(spec: AgentSpec, file: str) -> None:
    if spec.role != WORKER_ROLE:
        raise DefinitionError(file, "role", f"a subagent must have role '{WORKER_ROLE}'")
    if spec.description is None:
        raise DefinitionError(file, "description", "a subagent must declare a description")
