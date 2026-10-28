"""Unit tests for render_content (CallToolResult -> text)."""

from __future__ import annotations

from mcp.types import CallToolResult, ImageContent, TextContent

from tony.core.mcp import render_content


def test_text_blocks_are_joined_with_newlines() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="a"), TextContent(type="text", text="b")]
    )

    assert render_content(result) == "a\nb"


def test_non_text_blocks_are_skipped() -> None:
    result = CallToolResult(
        content=[
            ImageContent(type="image", data="aGk=", mimeType="image/png"),
            TextContent(type="text", text="solo texto"),
        ]
    )

    assert render_content(result) == "solo texto"


def test_structured_content_wins_as_json_without_ascii_escaping() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="ignorado")],
        structuredContent={"n": 1, "s": "añ"},
    )

    assert render_content(result) == '{"n": 1, "s": "añ"}'


def test_empty_content_renders_empty_string() -> None:
    assert render_content(CallToolResult(content=[])) == ""
