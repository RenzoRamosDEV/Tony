from pathlib import Path

import pytest

from tony.core.loader.skills import Skill, list_skills, read_skill_body

SKILLS = "agents/viernes/skills"


def write_skill(root, name, text, base=SKILLS):
    folder = root / base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(text)


def skill_text(name, description="Resume notas", body="Paso 1..."):
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def test_valid_skill_parsed(tmp_path):
    write_skill(tmp_path, "resumir", skill_text("resumir", "Resume notas en tres viñetas"))

    skills, errors = list_skills(tmp_path, "viernes")

    assert skills == [Skill("resumir", "Resume notas en tres viñetas", "Paso 1...")]
    assert errors == []


def test_subagent_skills_folder(tmp_path):
    write_skill(
        tmp_path, "buscar", skill_text("buscar"), base="agents/viernes/subagents/resumidor/skills"
    )

    skills, _ = list_skills(tmp_path, "viernes/resumidor")

    assert [skill.name for skill in skills] == ["buscar"]


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("sin frontmatter\n", None),
        (skill_text("resumen"), "name"),
        ("---\nname: roto\ndescription: d\nlicense: MIT\n---\nCuerpo\n", "license"),
        ("---\nname: roto\ndescription: ''\n---\nCuerpo\n", "description"),
        ("---\nname: roto\n---\nCuerpo\n", "description"),
        (skill_text("roto", body="   "), None),
    ],
)
def test_invalid_skill_reported_and_left_out(tmp_path, text, field):
    write_skill(tmp_path, "roto", text)
    write_skill(tmp_path, "ok", skill_text("ok"))

    skills, errors = list_skills(tmp_path, "viernes")

    assert [skill.name for skill in skills] == ["ok"]
    assert [(error.file, error.field) for error in errors] == [(f"{SKILLS}/roto/SKILL.md", field)]


def test_non_directories_and_folders_without_skill_md_ignored(tmp_path):
    (tmp_path / SKILLS / "vacia").mkdir(parents=True)
    (tmp_path / SKILLS / "suelto.md").write_text(skill_text("suelto"))

    assert list_skills(tmp_path, "viernes") == ([], [])


def test_sorted_by_name(tmp_path):
    for name in ["resumir", "buscar", "corregir"]:
        write_skill(tmp_path, name, skill_text(name))

    skills, _ = list_skills(tmp_path, "viernes")

    assert [skill.name for skill in skills] == ["buscar", "corregir", "resumir"]


def test_no_skills_folder_is_empty(tmp_path):
    assert list_skills(tmp_path, "viernes") == ([], [])


def test_read_skill_body_for_listed_name(tmp_path):
    write_skill(tmp_path, "resumir", skill_text("resumir", body="Paso 1\nPaso 2"))

    assert read_skill_body(tmp_path, "viernes", "resumir") == "Paso 1\nPaso 2"


def test_read_skill_body_invalid_skill_is_none(tmp_path):
    write_skill(tmp_path, "roto", "sin frontmatter\n")

    assert read_skill_body(tmp_path, "viernes", "roto") is None


@pytest.mark.parametrize("name", ["traducir", "../x", "a/b", "", "..", "RESUMIR"])
def test_read_skill_body_unknown_or_traversal_is_none(tmp_path, monkeypatch, name):
    write_skill(tmp_path, "resumir", skill_text("resumir"))
    write_skill(tmp_path, "x", skill_text("x"), base="agents/viernes")
    write_skill(tmp_path, "b", skill_text("b"), base=f"{SKILLS}/a")
    opened = []
    real_read = Path.read_text

    def spy_read(path, *args, **kwargs):
        opened.append(path.resolve())
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read)

    assert read_skill_body(tmp_path, "viernes", name) is None
    skills_root = (tmp_path / SKILLS).resolve()
    assert all(path.is_relative_to(skills_root) for path in opened)
    assert (tmp_path / "agents/viernes/x/SKILL.md").resolve() not in opened
    assert (tmp_path / SKILLS / "a/b/SKILL.md").resolve() not in opened
