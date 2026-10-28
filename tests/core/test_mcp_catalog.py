"""Unit tests for the tool catalog (specs/mcp-manager), no subprocess."""

from __future__ import annotations

from mcp.types import Tool, ToolAnnotations

from tony.core.mcp import ToolCatalog, ToolRef

ECHO_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def mcp_tool(name: str, destructive: bool | None = None, schema: dict | None = None) -> Tool:
    annotations = None if destructive is None else ToolAnnotations(destructiveHint=destructive)
    return Tool(
        name=name,
        description=f"desc {name}",
        inputSchema=schema or {"type": "object", "properties": {}},
        annotations=annotations,
    )


FAKE_TOOLS = {
    "fake": [
        mcp_tool("echo", schema=ECHO_SCHEMA),
        mcp_tool("fail"),
        mcp_tool("slow", destructive=False),
        mcp_tool("destroy", destructive=True),
    ]
}


def test_destructive_hint_marks_needs_confirm() -> None:
    catalog = ToolCatalog.build(FAKE_TOOLS, allow=None, confirm=[])

    destroy = catalog.get("fake.destroy")
    echo = catalog.get("fake.echo")
    assert (destroy.destructive, destroy.needs_confirm) == (True, True)
    assert (echo.destructive, echo.needs_confirm) == (False, False)
    assert catalog.get("fake.slow").destructive is False


def test_confirm_list_marks_needs_confirm_without_annotation() -> None:
    catalog = ToolCatalog.build(FAKE_TOOLS, allow=None, confirm=["fake.echo"])

    echo = catalog.get("fake.echo")
    assert (echo.destructive, echo.needs_confirm) == (False, True)


def test_tool_ref_fields_and_schema_are_preserved() -> None:
    catalog = ToolCatalog.build(FAKE_TOOLS, allow=None, confirm=[])

    assert catalog.get("fake.echo") == ToolRef(
        server="fake",
        name="echo",
        qualified="fake.echo",
        description="desc echo",
        input_schema=ECHO_SCHEMA,
        destructive=False,
        needs_confirm=False,
    )


def test_exact_allow_filters_other_tools() -> None:
    tools = {"fs": [mcp_tool("read_file"), mcp_tool("write_file")]}

    catalog = ToolCatalog.build(tools, allow=["fs.read_file"], confirm=[])

    assert catalog.qualified_names() == ["fs.read_file"]
    assert catalog.get("fs.write_file") is None
    assert "fs.write_file" not in catalog


def test_server_wildcard_allows_only_that_server() -> None:
    tools = {
        "fs": [mcp_tool("read_file"), mcp_tool("write_file")],
        "notion": [mcp_tool("search"), mcp_tool("create"), mcp_tool("update")],
    }

    catalog = ToolCatalog.build(tools, allow=["fs.*"], confirm=[])

    assert catalog.qualified_names() == ["fs.read_file", "fs.write_file"]


def test_absent_allow_keeps_every_tool() -> None:
    catalog = ToolCatalog.build(FAKE_TOOLS, allow=None, confirm=[])

    assert len(catalog) == 4
    assert catalog.qualified_names() == ["fake.echo", "fake.fail", "fake.slow", "fake.destroy"]


def test_empty_allow_keeps_nothing() -> None:
    assert len(ToolCatalog.build(FAKE_TOOLS, allow=[], confirm=[])) == 0


def test_servers_groups_refs_by_server_name() -> None:
    tools = {"fs": [mcp_tool("read_file")], "notion": [mcp_tool("search")]}

    catalog = ToolCatalog.build(tools, allow=None, confirm=[])

    assert {name: [r.name for r in refs] for name, refs in catalog.servers().items()} == {
        "fs": ["read_file"],
        "notion": ["search"],
    }


def test_colliding_qualified_names_keep_the_first_and_record_the_conflict() -> None:
    tools = {"a": [mcp_tool("b.c")], "a.b": [mcp_tool("c", destructive=True)]}

    catalog = ToolCatalog.build(tools, allow=None, confirm=[])

    assert catalog.qualified_names() == ["a.b.c"]
    ref = catalog.get("a.b.c")
    assert (ref.server, ref.name, ref.needs_confirm) == ("a", "b.c", False)
    assert catalog.conflicts == (
        "a.b.c: se ignora la tool 'c' del servidor 'a.b' porque colisiona con "
        "la tool 'b.c' del servidor 'a'",
    )


def test_catalog_without_collisions_has_no_conflicts() -> None:
    assert ToolCatalog.build(FAKE_TOOLS, allow=None, confirm=[]).conflicts == ()
