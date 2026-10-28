"""SKILL.md parsing and tolerant folder loading (specs/agent-skills)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tony.core.skills import SkillLoadError
from tony.core.skills.loader import load_skills, parse_skill

BODY = "1. Descarga la página con `fetch.fetch`.\n2. Extrae el contenido principal…"


def write_skill(skills_dir: Path, folder: str, frontmatter: str, body: str = BODY) -> Path:
    path = skills_dir / folder / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(frontmatter + body, encoding="utf-8")
    return path


def test_complete_skill_exposes_every_field(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path,
        "resumen-web",
        "---\nname: resumen-web\n"
        "description: Resume una página web en 5 viñetas con fuente y fecha.\n"
        'trigger: ["resume esta web", "resúmeme la página"]\n---\n',
    )

    skill = parse_skill(path)

    assert skill.name == "resumen-web"
    assert skill.description == "Resume una página web en 5 viñetas con fuente y fecha."
    assert skill.triggers == ["resume esta web", "resúmeme la página"]
    assert skill.body.startswith("1. Descarga la página")
    assert skill.path == tmp_path / "resumen-web"


def test_missing_trigger_means_no_triggers(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "a", "---\nname: a\ndescription: d\n---\n")

    assert parse_skill(path).triggers == []


def test_name_different_from_folder_is_rejected(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "resumen-web", "---\nname: resumen\ndescription: d\n---\n")

    with pytest.raises(SkillLoadError) as info:
        parse_skill(path)

    message = str(info.value)
    assert message.startswith("resumen-web: ")
    assert "resumen" in message and "name" in message
    assert info.value.skill == "resumen-web"


@pytest.mark.parametrize("length,valid", [(200, True), (201, False)])
def test_description_length_boundary(tmp_path: Path, length: int, valid: bool) -> None:
    path = write_skill(tmp_path, "a", f"---\nname: a\ndescription: {'x' * length}\n---\n")

    if valid:
        assert len(parse_skill(path).description) == 200
    else:
        with pytest.raises(SkillLoadError, match="description.*200"):
            parse_skill(path)


def test_missing_description_is_rejected(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "a", "---\nname: a\n---\n")

    with pytest.raises(SkillLoadError, match="description"):
        parse_skill(path)


def test_missing_frontmatter_is_rejected(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "a", "")

    with pytest.raises(SkillLoadError, match="frontmatter"):
        parse_skill(path)


def test_missing_skill_md_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()

    with pytest.raises(SkillLoadError, match="SKILL.md"):
        parse_skill(tmp_path / "a" / "SKILL.md")


def test_one_broken_skill_does_not_block_the_others(tmp_path: Path) -> None:
    write_skill(tmp_path, "a", "---\nname: a\ndescription: d\n---\n")
    write_skill(tmp_path, "b", "---\nname: b\n---\n")

    skills, errors = load_skills(tmp_path)

    assert [s.name for s in skills] == ["a"]
    assert len(errors) == 1
    assert errors[0].skill == "b" and "description" in errors[0].message


def test_missing_skills_folder_is_empty(tmp_path: Path) -> None:
    assert load_skills(tmp_path / "skills") == ([], [])


def test_load_skills_ignores_loose_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    write_skill(tmp_path, "a", "---\nname: a\ndescription: d\n---\n")

    skills, errors = load_skills(tmp_path)

    assert [s.name for s in skills] == ["a"] and errors == []


def test_error_messages_are_exact(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "resumen-web", "---\nname: resumen\ndescription: d\n---\n")
    with pytest.raises(SkillLoadError) as renamed:
        parse_skill(path)
    assert (
        str(renamed.value) == "resumen-web: name 'resumen' no coincide con la carpeta 'resumen-web'"
    )

    (tmp_path / "vacia").mkdir()
    with pytest.raises(SkillLoadError) as missing:
        parse_skill(tmp_path / "vacia" / "SKILL.md")
    assert str(missing.value) == "vacia: no existe SKILL.md"
