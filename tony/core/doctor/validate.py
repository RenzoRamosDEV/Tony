"""Configuration checks that need neither network nor processes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tony.core.config import EnvMap, TonySettings
from tony.core.loader import AgentLoadError, AgentSpec, load_agent

AGENT_HINT = (
    "revisa agents/{agent}/agent.md y tool/tool.json; define toda variable ${{VAR}} en config/.env"
)
SKILL_HINT = "revisa el frontmatter de agents/{agent}/skills/{skill}/SKILL.md"
SUBAGENT_HINT = "revisa agents/{agent}/subagents/{subagent}/"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool | None
    """True passed, False failed, None informative only."""
    detail: str = ""
    hint: str = ""

    @property
    def failed(self) -> bool:
        return self.ok is False


def validate_agent(
    agents_dir: Path, agent: str, settings: TonySettings, env: EnvMap
) -> list[CheckResult]:
    """Load one agent (with its skills and subagents) and report every problem found."""
    name = f"agente {agent}"
    try:
        spec = load_agent(agents_dir / agent, settings, env)
    except AgentLoadError as exc:
        return [CheckResult(name, False, exc.message, AGENT_HINT.format(agent=agent))]
    results = [CheckResult(name, True, f"{spec.role}, {spec.model}")]
    results.extend(_skill_results(agent, spec))
    for child, error in spec.subagent_errors.items():
        results.append(
            CheckResult(
                f"subagente {agent}/{child}",
                False,
                error,
                SUBAGENT_HINT.format(agent=agent, subagent=child),
            )
        )
    for child, child_spec in spec.subagents.items():
        results.append(CheckResult(f"subagente {agent}/{child}", True, child_spec.model))
        results.extend(_skill_results(f"{agent}/subagents/{child}", child_spec))
    return results


def _skill_results(agent: str, spec: AgentSpec) -> list[CheckResult]:
    results = [CheckResult(f"skill {agent}/{s.name}", True, s.description) for s in spec.skills]
    for error in spec.skill_errors:
        skill, _, reason = error.partition(": ")
        results.append(
            CheckResult(
                f"skill {agent}/{skill}", False, reason, SKILL_HINT.format(agent=agent, skill=skill)
            )
        )
    return results
