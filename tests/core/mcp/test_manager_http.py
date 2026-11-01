from tests.fakes.http_server import running_http_mcp_server
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager


async def test_lists_http_tools_with_resolved_headers(tmp_path):
    masker = SecretMasker()
    async with running_http_mcp_server() as remote:
        spec = ToolSpec.model_validate(
            {
                "mcpServers": {
                    "remote": {
                        "url": "${REMOTE_URL}",
                        "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"},
                    }
                }
            }
        )
        variables = {"REMOTE_URL": remote.url, "REMOTE_TOKEN": "tok3n"}
        async with McpManager(
            spec, variables=variables, masker=masker, sink=ListEventSink(), log_dir=tmp_path
        ) as manager:
            ids = [tool.id for tool in manager.tools]
            descriptions = {tool.id: tool.description for tool in manager.tools}
            status = manager.status["remote"]

    assert ids == ["remote.ping", "remote.bare"]
    assert descriptions == {"remote.ping": "Answer pong.", "remote.bare": ""}
    assert status.up is True
    assert remote.authorizations and set(remote.authorizations) == {"Bearer tok3n"}
    assert masker.mask("tok3n") == "***"
