import json

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.loader.subagents import list_subagents, load_subagent

BASE = "agents/viernes/subagents"
NATIVE = {"read_skill", "run_subagent"}


def agent_md(name, role="worker", description="Resume textos largos"):
    lines = [
        "---",
        f"name: {name}",
        f"role: {role}",
        "model: claude-sonnet",
        "persona: {language: es, tone: directo}",
        "voice: {tts: kokoro/em_alex}",
    ]
    if description is not None:
        lines.append(f"description: {description}")
    return "\n".join([*lines, "---", "Resume.", ""])


def make_subagent(root, name, md=None, tools=None):
    folder = root / BASE / name
    (folder / "tool").mkdir(parents=True)
    (folder / "agent.md").write_text(md if md is not None else agent_md(name))
    (folder / "tool" / "tool.json").write_text(json.dumps(tools or {"mcpServers": {}}))


def load(root, name):
    return load_subagent(root, "viernes", name, TonyConfig(), native_tools=NATIVE)


def error_of(root, name):
    with pytest.raises(DefinitionError) as info:
        load(root, name)
    return info.value.file, info.value.field


def test_valid_subagent_loads_with_key(tmp_path):
    make_subagent(tmp_path, "resumidor", tools={"mcpServers": {}, "native": ["read_skill"]})

    agent = load(tmp_path, "resumidor")

    assert (agent.name, agent.spec.role, agent.spec.description, agent.tools.native) == (
        "viernes/resumidor",
        "worker",
        "Resume textos largos",
        ["read_skill"],
    )


def test_non_worker_role_rejected(tmp_path):
    make_subagent(tmp_path, "resumidor", md=agent_md("resumidor", role="front"))

    assert error_of(tmp_path, "resumidor") == (f"{BASE}/resumidor/agent.md", "role")


def test_missing_description_rejected(tmp_path):
    make_subagent(tmp_path, "resumidor", md=agent_md("resumidor", description=None))

    assert error_of(tmp_path, "resumidor") == (f"{BASE}/resumidor/agent.md", "description")


def test_nested_subagents_refused(tmp_path):
    make_subagent(tmp_path, "resumidor", tools={"mcpServers": {}, "native": ["run_subagent"]})

    assert error_of(tmp_path, "resumidor") == (f"{BASE}/resumidor/tool/tool.json", "native")


@pytest.mark.parametrize("name", ["traductor", "..", "../viernes", "a/b", "", "."])
def test_unknown_or_traversal_not_found(tmp_path, name):
    make_subagent(tmp_path, "resumidor")
    make_subagent(tmp_path, "a/b")

    assert load(tmp_path, name) is None


def test_no_subagents_folder_not_found(tmp_path):
    assert load(tmp_path, "resumidor") is None


def test_listing_sorted_and_skips_invalid(tmp_path):
    make_subagent(tmp_path, "traductor", md=agent_md("traductor", description="Traduce"))
    make_subagent(tmp_path, "resumidor")
    make_subagent(tmp_path, "roto", md="sin frontmatter")
    make_subagent(tmp_path, "frente", md=agent_md("frente", role="front"))
    make_subagent(tmp_path, "mudo", md=agent_md("mudo", description=None))
    (tmp_path / BASE / "suelto.md").write_text(agent_md("suelto"))

    assert list_subagents(tmp_path, "viernes", TonyConfig()) == [
        ("resumidor", "Resume textos largos"),
        ("traductor", "Traduce"),
    ]


def test_listing_without_folder_is_empty(tmp_path):
    assert list_subagents(tmp_path, "viernes", TonyConfig()) == []
