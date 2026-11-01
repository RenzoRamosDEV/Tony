from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager, ServerStatus


async def test_on_status_called_once_per_declared_server(tmp_path):
    statuses = []
    spec = ToolSpec.model_validate(
        {
            "mcpServers": {
                "filesystem": fake_fs_entry(str(tmp_path)),
                "broken": {"command": "/nonexistent/tony-no-such-cmd", "args": ["s3cr3t"]},
            }
        }
    )
    manager = McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker({"s3cr3t"}),
        sink=ListEventSink(),
        log_dir=tmp_path / "mcp",
        on_status=lambda server, status: statuses.append((server, status)),
    )

    async with manager:
        pass

    assert sorted(server for server, _ in statuses) == ["broken", "filesystem"]
    by_server = dict(statuses)
    assert by_server["filesystem"] == ServerStatus(up=True)
    assert by_server["broken"].up is False
    assert "tony-no-such-cmd" in by_server["broken"].reason
    assert "s3cr3t" not in by_server["broken"].reason


async def test_on_status_defaults_to_no_op(tmp_path):
    spec = ToolSpec.model_validate({"mcpServers": {"fs": fake_fs_entry(str(tmp_path))}})
    manager = McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path / "mcp",
    )

    async with manager:
        assert manager.status["fs"].up
