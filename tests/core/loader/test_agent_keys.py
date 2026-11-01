import pytest

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.loader.agent import load_agent
from tony.core.loader.tool_json import ToolSpec, agent_folder, tool_file, tool_json_keys

SUB_MD = """---
name: resumidor
role: worker
model: claude-sonnet
persona: {language: es, tone: directo}
voice: {tts: kokoro/em_alex}
description: Resume textos largos
---
Resume.
"""


@pytest.mark.parametrize(
    ("key", "folder"),
    [("viernes", "agents/viernes/"), ("viernes/resumidor", "agents/viernes/subagents/resumidor/")],
)
def test_agent_folder(key, folder):
    assert agent_folder(key) == folder


@pytest.mark.parametrize(
    ("key", "file"),
    [
        ("viernes", "agents/viernes/tool/tool.json"),
        ("viernes/resumidor", "agents/viernes/subagents/resumidor/tool/tool.json"),
    ],
)
def test_tool_file(key, file):
    assert tool_file(key) == file


@pytest.mark.parametrize(
    "key", ["", "..", "viernes/..", "../x", "/x", "x/", "a/b/c", "a//b", ".", "viernes/."]
)
def test_invalid_keys_rejected(key):
    with pytest.raises(DefinitionError) as info:
        agent_folder(key)
    assert "agent key" in info.value.message


def make_subagent(root, tool_json="not json"):
    folder = root / "agents" / "viernes" / "subagents" / "resumidor"
    (folder / "tool").mkdir(parents=True)
    (folder / "agent.md").write_text(SUB_MD)
    (folder / "tool" / "tool.json").write_text(tool_json)


def test_load_agent_by_subagent_key(tmp_path):
    make_subagent(tmp_path, '{"mcpServers": {}}')

    agent = load_agent(tmp_path, "viernes/resumidor", TonyConfig(), native_tools=set())

    assert (agent.name, agent.spec.name, agent.spec.description) == (
        "viernes/resumidor",
        "resumidor",
        "Resume textos largos",
    )


def test_tools_override_skips_tool_json(tmp_path):
    make_subagent(tmp_path, "not json")
    override = ToolSpec(mcp_servers={})

    agent = load_agent(
        tmp_path, "viernes/resumidor", TonyConfig(), native_tools=set(), tools=override
    )

    assert agent.tools is override


def test_subagent_missing_folder_names_it(tmp_path):
    with pytest.raises(DefinitionError) as info:
        load_agent(tmp_path, "viernes/nadie", TonyConfig(), native_tools=set())
    assert info.value.file == "agents/viernes/subagents/nadie/"


def test_tool_json_keys_in_path_order(tmp_path):

    for file in [
        "agents/viernes/tool/tool.json",
        "agents/jarvis/tool/tool.json",
        "agents/viernes/subagents/resumidor/tool/tool.json",
        "agents/viernes/subagents/a/tool/tool.json",
        "agents/edith/policy.yaml",
        "agents/x/tool/other.json",
    ]:
        (tmp_path / file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / file).write_text("{}")

    assert tool_json_keys(tmp_path) == ["jarvis", "viernes", "viernes/a", "viernes/resumidor"]
