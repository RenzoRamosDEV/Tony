from pathlib import Path

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.loader.agent import load_agent

REPO = Path(__file__).resolve().parents[3]

AGENT_MD = """---
name: viernes
role: worker
model: claude-sonnet
persona: {language: es, tone: directo}
voice: {tts: kokoro/em_alex}
---
Prompt.
"""


def make_agent(root, agent_md=AGENT_MD, tool_json='{"mcpServers": {}}'):
    folder = root / "agents" / "viernes"
    (folder / "tool").mkdir(parents=True)
    if agent_md is not None:
        (folder / "agent.md").write_text(agent_md)
    if tool_json is not None:
        (folder / "tool" / "tool.json").write_text(tool_json)


def test_bundled_viernes_loads_with_default_config():
    agent = load_agent(REPO, "viernes", TonyConfig(), native_tools=set())

    assert (agent.spec.role, agent.spec.model) == ("worker", "claude-sonnet")
    assert agent.spec.persona.language == "es"
    assert agent.spec.voice.tts.startswith("kokoro/")
    assert "objetivo" in agent.spec.system_prompt and "errores" in agent.spec.system_prompt
    filesystem = agent.tools.mcp_servers["filesystem"]
    assert filesystem.command == "npx"
    assert "@modelcontextprotocol/server-filesystem" in filesystem.args
    assert "${HOME}/notas" in filesystem.args
    assert agent.tools.native == []


def test_loads_agent_from_root(tmp_path):
    make_agent(tmp_path)

    agent = load_agent(tmp_path, "viernes", TonyConfig(), native_tools=set())

    assert (agent.name, agent.spec.system_prompt, agent.tools.mcp_servers) == (
        "viernes",
        "Prompt.",
        {},
    )


def test_unknown_agent_names_missing_folder(tmp_path):
    with pytest.raises(DefinitionError) as info:
        load_agent(tmp_path, "nadie", TonyConfig(), native_tools=set())

    assert info.value.file == "agents/nadie/"


def test_missing_agent_md_names_file(tmp_path):
    make_agent(tmp_path, agent_md=None)

    with pytest.raises(DefinitionError) as info:
        load_agent(tmp_path, "viernes", TonyConfig(), native_tools=set())

    assert info.value.file == "agents/viernes/agent.md"


def test_model_alias_checked_against_configured_models(tmp_path):
    make_agent(tmp_path)

    with pytest.raises(DefinitionError) as info:
        load_agent(tmp_path, "viernes", TonyConfig(models={"x": "y"}), native_tools=set())

    assert (info.value.file, info.value.field) == ("agents/viernes/agent.md", "model")


def test_native_tools_checked_against_registry(tmp_path):
    make_agent(tmp_path, tool_json='{"mcpServers": {}, "native": ["now"]}')

    agent = load_agent(tmp_path, "viernes", TonyConfig(), native_tools={"now"})

    assert agent.tools.native == ["now"]


GUARD_MD = """---
name: edith
role: guard
model: claude-haiku
persona: {language: es, tone: formal}
voice: {tts: kokoro/ef_dora}
---
Prompt.
"""


def make_guard(root, with_tool_folder):
    folder = root / "agents" / "edith"
    folder.mkdir(parents=True)
    (folder / "agent.md").write_text(GUARD_MD)
    if with_tool_folder:
        (folder / "tool").mkdir()


def test_guard_without_tool_folder_loads_with_no_tools(tmp_path):
    make_guard(tmp_path, with_tool_folder=False)

    agent = load_agent(tmp_path, "edith", TonyConfig(), native_tools={"now"})

    assert agent.spec.role == "guard"
    assert (agent.tools.mcp_servers, agent.tools.native) == ({}, [])


def test_guard_with_tool_folder_rejected(tmp_path):
    make_guard(tmp_path, with_tool_folder=True)

    with pytest.raises(DefinitionError) as info:
        load_agent(tmp_path, "edith", TonyConfig(), native_tools=set())

    assert (info.value.file, info.value.field) == ("agents/edith/tool/", None)
    assert "guard agent has no tools" in info.value.message


@pytest.mark.parametrize("role", ["worker", "front"])
def test_non_guard_without_tool_json_names_expected_file(tmp_path, role):
    make_agent(tmp_path, agent_md=AGENT_MD.replace("role: worker", f"role: {role}"), tool_json=None)

    with pytest.raises(DefinitionError) as info:
        load_agent(tmp_path, "viernes", TonyConfig(), native_tools=set())

    assert info.value.file == "agents/viernes/tool/tool.json"
