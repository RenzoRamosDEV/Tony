from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager


def manager_for(tmp_path, servers, variables=None, masker=None):
    spec = ToolSpec.model_validate({"mcpServers": servers})
    return McpManager(
        spec,
        variables=variables or {},
        masker=masker or SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path / "logs" / "mcp",
    )


async def test_lists_stdio_tools_as_server_dot_tool(tmp_path):
    servers = {"filesystem": fake_fs_entry("${NOTES}")}

    async with manager_for(tmp_path, servers, {"NOTES": str(tmp_path)}) as manager:
        ids = [tool.id for tool in manager.tools]
        status = manager.status["filesystem"]

    assert sorted(ids) == [
        "filesystem.echo_env",
        "filesystem.list_directory",
        "filesystem.read_file",
        "filesystem.sleep",
    ]
    assert (status.up, status.reason) == (True, None)


async def test_catalog_keeps_description_and_schema(tmp_path):
    async with manager_for(tmp_path, {"fs": fake_fs_entry(str(tmp_path))}) as manager:
        read_file = next(tool for tool in manager.tools if tool.id == "fs.read_file")

    assert read_file.server == "fs" and read_file.name == "read_file"
    assert read_file.description == "Return the content of a file."
    assert read_file.input_schema["properties"]["path"]["type"] == "string"


async def test_placeholders_resolved_at_start_and_registered_as_secrets(tmp_path):
    masker = SecretMasker()
    servers = {"fs": fake_fs_entry(str(tmp_path), env={"TOKEN": "${GITHUB_TOKEN}"})}
    manager = manager_for(tmp_path, servers, {"GITHUB_TOKEN": "s3cr3t"}, masker)

    assert masker.mask("s3cr3t") == "s3cr3t"
    async with manager:
        assert masker.mask("s3cr3t") == "***"

    assert manager.spec.mcp_servers["fs"].env == {"TOKEN": "${GITHUB_TOKEN}"}


async def test_server_stderr_goes_to_per_server_log_file(tmp_path):
    async with manager_for(tmp_path, {"fs": fake_fs_entry(str(tmp_path))}):
        pass

    assert (tmp_path / "logs" / "mcp" / "fs.log").is_file()
