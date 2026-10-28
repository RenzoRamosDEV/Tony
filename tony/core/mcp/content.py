"""Pure conversion of an MCP CallToolResult into the text handed to the model."""

from __future__ import annotations

import json

from mcp.types import CallToolResult, TextContent


def render_content(result: CallToolResult) -> str:
    """structuredContent as JSON when present; otherwise the text blocks joined by newlines."""
    if result.structured_content is not None:
        return json.dumps(result.structured_content, ensure_ascii=False)
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))
