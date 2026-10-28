"""The agents shipped in agents/ load and declare the expected policies."""

from __future__ import annotations

from pathlib import Path

from mcp.types import Tool

from tony.core.config import load_settings
from tony.core.loader import AgentSpec, StdioServer, load_agent, load_all
from tony.core.mcp import ToolCatalog

AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
FILESYSTEM_TOOLS = [
    "read_file",
    "read_text_file",
    "list_directory",
    "write_file",
    "edit_file",
    "move_file",
]


def simulated_catalog(confirm: list[str]) -> ToolCatalog:
    tools = {
        "filesystem": [
            Tool(name=name, description=name, inputSchema={"type": "object"})
            for name in FILESYSTEM_TOOLS
        ]
    }
    return ToolCatalog.build(tools, allow=None, confirm=confirm)


def test_viernes_is_a_worker_with_filesystem_mcp() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    assert spec.role == "worker"
    assert spec.model == "claude-sonnet"
    assert "TaskResult" in spec.system_prompt
    assert isinstance(spec.tools.mcpServers["filesystem"], StdioServer)
    assert spec.tools.mcpServers["filesystem"].args[-1] == "/home/x/notas"
    assert spec.tools.allow is None


def test_viernes_marks_writes_as_needs_confirm() -> None:
    spec = load_agent(AGENTS_DIR / "viernes", load_settings(None), {"HOME": "/home/x"})

    catalog = simulated_catalog(spec.tools.confirm)

    assert {ref.name for ref in catalog if ref.needs_confirm} == {
        "write_file",
        "edit_file",
        "move_file",
    }
    assert catalog.get("filesystem.read_file").needs_confirm is False


def test_load_all_returns_jarvis_and_viernes_without_errors() -> None:
    loaded = load_all(AGENTS_DIR, load_settings(None), {"HOME": "/home/x"})

    assert set(loaded) == {"jarvis", "viernes"}
    assert all(isinstance(spec, AgentSpec) for spec in loaded.values())
    assert loaded["jarvis"].role == "front"
    assert loaded["jarvis"].tools.native == ["delegate", "remember", "set_reply_mode"]
    assert loaded["jarvis"].tools.mcpServers == {}
