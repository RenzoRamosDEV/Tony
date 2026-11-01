from tony.core.loader.skills import Skill
from tony.core.orchestrator.prompt_sections import with_sections

BODY = "Eres Viernes."


def test_no_sections_when_both_empty():
    assert with_sections(BODY, [], []) == BODY


def test_skills_section_sorted_without_bodies():
    skills = [Skill("resumir", "Resume notas", "Paso 1..."), Skill("buscar", "Busca", "Paso B")]

    prompt = with_sections(BODY, skills, [])

    assert prompt == f"{BODY}\n\n## Skills\n\n- buscar: Busca\n- resumir: Resume notas"
    assert "Paso" not in prompt


def test_subagents_section_sorted():
    prompt = with_sections(BODY, [], [("traductor", "Traduce"), ("resumidor", "Resume")])

    assert prompt == f"{BODY}\n\n## Subagentes\n\n- resumidor: Resume\n- traductor: Traduce"


def test_both_sections_skills_first():
    prompt = with_sections(BODY, [Skill("a", "A", "x")], [("s", "S")])

    assert prompt == f"{BODY}\n\n## Skills\n\n- a: A\n\n## Subagentes\n\n- s: S"
