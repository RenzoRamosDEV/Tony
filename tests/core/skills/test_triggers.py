"""Automatic activation by trigger phrases (specs/agent-skills)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tony.core.skills import SkillSpec
from tony.core.skills.triggers import matched_skills, normalize, skill_blocks


def skill(name: str, triggers: list[str], body: str = "cuerpo") -> SkillSpec:
    return SkillSpec(name=name, description="d", triggers=triggers, body=body, path=Path("/s"))


RESUMEN = skill("resumen-web", ["resume esta web", "resúmeme la página"], "1. Descarga la página")


@pytest.mark.parametrize(
    "text,expected",
    [("RESÚMEME la Página", "resumeme la pagina"), ("¿Qué hora es?", "¿que hora es?"), ("", "")],
)
def test_normalize_drops_accents_and_case(text: str, expected: str) -> None:
    assert normalize(text) == expected


@pytest.mark.parametrize(
    "text", ["Resume esta web: https://x.y", "RESUMEME LA PAGINA de hoy", "resúmeme la página"]
)
def test_trigger_matches_ignoring_case_and_accents(text: str) -> None:
    assert matched_skills(text, [RESUMEN]) == [RESUMEN]


@pytest.mark.parametrize("text", ["¿qué hora es?", "", "resume esta"])
def test_no_match_without_a_trigger_phrase(text: str) -> None:
    assert matched_skills(text, [RESUMEN]) == []
    assert skill_blocks(text, [RESUMEN]) == ""


def test_each_activated_skill_is_injected_once() -> None:
    a = skill("a", ["informe", "el informe"], "cuerpo a")
    b = skill("b", ["semanal"], "cuerpo b")

    blocks = skill_blocks("prepara el informe semanal", [a, b])

    assert blocks.count('<skill name="a">') == 1
    assert blocks.count('<skill name="b">') == 1
    assert blocks.index('<skill name="a">') < blocks.index('<skill name="b">')


def test_block_format_wraps_the_body() -> None:
    assert skill_blocks("resume esta web", [RESUMEN]) == (
        '<skill name="resumen-web">\n1. Descarga la página\n</skill>\n\n'
    )


def test_skill_without_triggers_never_activates() -> None:
    assert matched_skills("cualquier cosa", [skill("x", [])]) == []
