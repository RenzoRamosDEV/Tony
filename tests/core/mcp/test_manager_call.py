import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

from tests.fakes.processes import processes_mentioning
from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager, _to_reply
from tony.core.orchestrator.ports import ToolReply


@pytest.fixture
def notes(tmp_path):
    folder = tmp_path / "notas-call-test"
    folder.mkdir()
    (folder / "a.md").write_text("# Nota A\nhola")
    return folder


def manager_for(notes, env=None):
    entry = fake_fs_entry(str(notes), **({"env": env} if env else {}))
    spec = ToolSpec.model_validate({"mcpServers": {"fs": entry}})
    return McpManager(
        spec,
        variables=secret_variables({"TOKEN_VALUE": "s3cr3t"}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=notes.parent / "logs",
    )


async def test_successful_call_returns_text(notes):
    async with manager_for(notes) as manager:
        reply = await manager.call("fs.read_file", {"path": "a.md"})

    assert reply == ToolReply(text="# Nota A\nhola", is_error=False)


async def test_mcp_error_result_becomes_error_reply(notes):
    async with manager_for(notes) as manager:
        reply = await manager.call("fs.read_file", {"path": "nada.md"})

    assert reply.is_error is True
    assert "nada.md" in reply.text


@pytest.mark.parametrize("tool_id", ["fs.write_file", "other.read_file", "read_file", ""])
async def test_unknown_tool_id_is_not_available(notes, tool_id):
    async with manager_for(notes) as manager:
        reply = await manager.call(tool_id, {})

    assert reply == ToolReply(text=f"tool {tool_id} is not available", is_error=True)


async def test_server_process_receives_resolved_env(notes):
    async with manager_for(notes, env={"TOKEN": "${TOKEN_VALUE}"}) as manager:
        reply = await manager.call("fs.echo_env", {"name": "TOKEN"})

    assert reply.text == "s3cr3t"


async def test_stdio_process_exits_after_context_closes(notes):
    async with manager_for(notes):
        assert processes_mentioning(str(notes)) != []

    assert processes_mentioning(str(notes)) == []


def test_non_text_blocks_are_named_and_blocks_joined_by_newline():
    result = CallToolResult(
        content=[
            TextContent(type="text", text="uno"),
            ImageContent(type="image", data="AA==", mime_type="image/png"),
            TextContent(type="text", text="dos"),
        ],
        is_error=False,
    )

    assert _to_reply(result) == ToolReply(text="uno\n[image]\ndos", is_error=False)
