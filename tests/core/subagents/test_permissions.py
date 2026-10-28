"""Child permissions as the intersection with the parent (specs/subagents)."""

from __future__ import annotations

import pytest

from tests.core.runner_helpers import mcp_tool
from tony.core.loader import StdioServer, ToolConfig
from tony.core.mcp import ToolCatalog
from tony.core.subagents.permissions import ChildPolicy, child_policy, effective_catalog

FS = StdioServer(command="fs")
NOTION = StdioServer(command="notion")
FETCH = StdioServer(command="fetch")
TOOLS = {
    "fs": [mcp_tool("read_file"), mcp_tool("write_file")],
    "notion": [mcp_tool("search")],
}


def parent_config(allow: list[str] | None = None, confirm: list[str] | None = None) -> ToolConfig:
    return ToolConfig(mcpServers={"fs": FS, "notion": NOTION}, allow=allow, confirm=confirm or [])


def child_names(parent: ToolConfig, child: ToolConfig) -> list[str]:
    parent_catalog = ToolCatalog.build(TOOLS, parent.allow, parent.confirm)
    policy = child_policy(parent, child, parent_is_subagent=False)
    return sorted(effective_catalog(parent_catalog, policy).qualified_names())


@pytest.mark.parametrize(
    "parent_allow,child,expected",
    [
        (["fs.*"], ToolConfig(), ["fs.read_file", "fs.write_file"]),
        (["fs.*"], ToolConfig(allow=["fs.read_file", "notion.*"]), ["fs.read_file"]),
        (None, ToolConfig(allow=["fs.read_file"]), ["fs.read_file"]),
    ],
)
def test_effective_catalog_is_the_intersection(parent_allow, child, expected) -> None:
    assert child_names(parent_config(allow=parent_allow), child) == expected


def test_empty_child_inherits_the_parent_exactly() -> None:
    parent = parent_config(confirm=["fs.write_file"])

    policy = child_policy(parent, ToolConfig(), parent_is_subagent=False)

    assert policy == ChildPolicy(
        servers=parent.mcpServers,
        new_servers=[],
        allow_parent=None,
        allow_child=None,
        confirm=["fs.write_file"],
        warnings=[],
    )


def test_parent_confirm_is_always_inherited() -> None:
    parent = parent_config(confirm=["fs.write_file"])
    policy = child_policy(parent, ToolConfig(confirm=[]), parent_is_subagent=False)

    catalog = effective_catalog(ToolCatalog.build(TOOLS, None, parent.confirm), policy)

    assert catalog.get("fs.write_file").needs_confirm is True
    assert catalog.get("fs.read_file").needs_confirm is False


def test_child_can_add_confirm_entries() -> None:
    parent = parent_config()
    parent_catalog = ToolCatalog.build(TOOLS, None, parent.confirm)
    policy = child_policy(parent, ToolConfig(confirm=["fs.read_file"]), parent_is_subagent=False)

    child_catalog = effective_catalog(parent_catalog, policy)

    assert policy.confirm == ["fs.read_file"]
    assert child_catalog.get("fs.read_file").needs_confirm is True
    assert parent_catalog.get("fs.read_file").needs_confirm is False


def test_new_server_is_allowed_when_the_parent_is_not_a_subagent() -> None:
    child = ToolConfig(mcpServers={"fetch": FETCH})

    policy = child_policy(parent_config(), child, parent_is_subagent=False)

    assert policy.new_servers == ["fetch"]
    assert policy.servers == {"fs": FS, "notion": NOTION, "fetch": FETCH}
    assert policy.warnings == []


def test_new_server_tools_pass_through_the_parent_allow() -> None:
    policy = child_policy(
        parent_config(allow=["fs.*"]),
        ToolConfig(mcpServers={"notion": NOTION}),
        parent_is_subagent=False,
    )

    own = ToolCatalog.build({"notion": [mcp_tool("search")]}, policy.allow_child, policy.confirm)

    assert policy.allow_parent == ["fs.*"]
    assert own.restrict(policy.allow_parent).qualified_names() == []


def test_new_server_is_rejected_with_a_warning_when_the_parent_is_a_subagent() -> None:
    policy = child_policy(
        parent_config(), ToolConfig(mcpServers={"fetch": FETCH}), parent_is_subagent=True
    )

    assert policy.new_servers == []
    assert "fetch" not in policy.servers
    assert len(policy.warnings) == 1 and "fetch" in policy.warnings[0]


def test_repeated_server_name_uses_the_parent_definition() -> None:
    other = StdioServer(command="otro-fs")

    policy = child_policy(parent_config(), ToolConfig(mcpServers={"fs": other}), False)

    assert policy.servers["fs"] == FS
    assert policy.new_servers == []


def test_child_allow_patterns_are_kept_for_its_own_servers() -> None:
    policy = child_policy(parent_config(), ToolConfig(allow=["fetch.*"]), False)

    assert policy.allow_child == ["fetch.*"]
