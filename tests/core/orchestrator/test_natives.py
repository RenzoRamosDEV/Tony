import pytest

from tony.core.mcp.native import NativeScope
from tony.core.orchestrator.natives import NATIVE_TOOLS, read_skill
from tony.core.orchestrator.ports import ToolReply


def write_skill(root, base, name, body):
    folder = root / base / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{body}\n")


def bound(root, agent="viernes"):
    return read_skill(NativeScope(root=root, agent=agent))


async def call(root, name, agent="viernes"):
    return await bound(root, agent).run({"name": name})


def test_registry_uses_read_skill():
    assert NATIVE_TOOLS["read_skill"] is read_skill


def test_input_schema_requires_name(tmp_path):
    schema = bound(tmp_path).input_schema

    assert schema["required"] == ["name"]
    assert schema["properties"]["name"]["type"] == "string"


@pytest.mark.parametrize(
    ("agent", "base"),
    [("viernes", "agents/viernes"), ("viernes/resumidor", "agents/viernes/subagents/resumidor")],
)
async def test_body_returned_from_own_folder(tmp_path, agent, base):
    write_skill(tmp_path, "agents/viernes", "resumir", "Cuerpo de Viernes")
    write_skill(tmp_path, "agents/viernes/subagents/resumidor", "resumir", "Cuerpo del sub")
    expected = "Cuerpo de Viernes" if agent == "viernes" else "Cuerpo del sub"

    assert await call(tmp_path, "resumir", agent) == ToolReply(text=expected)


async def test_unknown_lists_available(tmp_path):
    write_skill(tmp_path, "agents/viernes", "resumir", "r")
    write_skill(tmp_path, "agents/viernes", "buscar", "b")

    assert await call(tmp_path, "traducir") == ToolReply(
        text="skill 'traducir' not found; available: buscar, resumir", is_error=True
    )


async def test_no_skills_available_none(tmp_path):
    assert await call(tmp_path, "x") == ToolReply(
        text="skill 'x' not found; available: none", is_error=True
    )


@pytest.mark.parametrize("name", ["../../jarvis/skills/x", "..", "a/b", ""])
async def test_traversal_not_found(tmp_path, name):
    write_skill(tmp_path, "agents/jarvis", "x", "secreto")

    reply = await call(tmp_path, name)

    assert reply.is_error and reply.text.startswith(f"skill '{name}' not found")


async def test_missing_name_argument_not_found(tmp_path):
    reply = await bound(tmp_path).run({})

    assert reply.is_error and "not found" in reply.text


async def test_skill_added_after_binding_is_readable(tmp_path):
    tool = bound(tmp_path)
    write_skill(tmp_path, "agents/viernes", "nueva", "Nuevo cuerpo")

    assert await tool.run({"name": "nueva"}) == ToolReply(text="Nuevo cuerpo")
