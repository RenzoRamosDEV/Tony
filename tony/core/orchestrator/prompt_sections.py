from collections.abc import Iterable

from tony.core.loader.skills import Skill


def with_sections(body: str, skills: Iterable[Skill], subagents: Iterable[tuple[str, str]]) -> str:
    sections = [body]
    sections += _section("Skills", ((skill.name, skill.description) for skill in skills))
    sections += _section("Subagentes", subagents)
    return "\n\n".join(sections)


def _section(title: str, entries: Iterable[tuple[str, str]]) -> list[str]:
    lines = [f"- {name}: {description}" for name, description in sorted(entries)]
    return [f"## {title}", "\n".join(lines)] if lines else []
