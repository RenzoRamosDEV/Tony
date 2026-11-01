from collections.abc import Iterable
from pathlib import Path

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.loader.agent import AgentDefinition
from tony.core.loader.skills import Skill, list_skills
from tony.core.loader.subagents import list_subagents

READ_SKILL = "read_skill"
RUN_SUBAGENT = "run_subagent"


def agent_prompt(
    root: Path, agent: AgentDefinition, config: TonyConfig
) -> tuple[str, list[DefinitionError]]:
    """The agent's system prompt with the skills and subagents its natives can reach."""
    skills: list[Skill] = []
    errors: list[DefinitionError] = []
    if READ_SKILL in agent.tools.native:
        skills, errors = list_skills(root, agent.name)
    subagents = []
    if RUN_SUBAGENT in agent.tools.native:
        subagents = list_subagents(root, agent.name, config)
    return with_sections(agent.spec.system_prompt, skills, subagents), errors


def with_sections(body: str, skills: Iterable[Skill], subagents: Iterable[tuple[str, str]]) -> str:
    sections = [body]
    sections += _section("Skills", ((skill.name, skill.description) for skill in skills))
    sections += _section("Subagentes", subagents)
    return "\n\n".join(sections)


def _section(title: str, entries: Iterable[tuple[str, str]]) -> list[str]:
    lines = [f"- {name}: {description}" for name, description in sorted(entries)]
    return [f"## {title}", "\n".join(lines)] if lines else []
