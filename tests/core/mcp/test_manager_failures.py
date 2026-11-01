import sys

import pytest

from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager

HANGING = {"command": sys.executable, "args": ["-c", "import time; time.sleep(30)"]}


def manager_for(tmp_path, broken, sink, variables=None, timeout=10.0):
    spec = ToolSpec.model_validate(
        {"mcpServers": {"broken": broken, "filesystem": fake_fs_entry(str(tmp_path))}}
    )
    return McpManager(
        spec,
        variables=variables or {},
        masker=SecretMasker(),
        sink=sink,
        log_dir=tmp_path / "logs" / "mcp",
        connect_timeout=timeout,
    )


@pytest.mark.parametrize(
    ("broken", "variables", "timeout", "reason_part"),
    [
        ({"command": "/nonexistent/tony-no-such-cmd"}, {}, 10.0, "tony-no-such-cmd"),
        (
            {"command": "echo", "args": ["${MISSING_VAR}"]},
            {"SECRET": "s3cr3t"},
            10.0,
            "MISSING_VAR",
        ),
        (HANGING, {}, 3.0, "timeout"),
    ],
    ids=["missing-command", "undefined-variable", "hang"],
)
async def test_failed_server_is_isolated(tmp_path, capsys, broken, variables, timeout, reason_part):
    sink = ListEventSink()

    async with manager_for(tmp_path, broken, sink, variables, timeout) as manager:
        ids = {tool.id for tool in manager.tools}
        status = manager.status

    assert status["broken"].up is False
    assert reason_part in status["broken"].reason
    assert status["filesystem"].up is True
    assert "filesystem.read_file" in ids
    assert not any(tool_id.startswith("broken.") for tool_id in ids)
    [event] = sink.events
    assert event["type"] == "error" and event["source"] == "mcp.broken"
    assert "broken" in event["message"] and reason_part in event["message"]
    stderr = capsys.readouterr().err
    assert "broken" in stderr and reason_part in stderr
    assert "s3cr3t" not in stderr + event["message"]


async def test_working_servers_emit_no_error(tmp_path):
    sink = ListEventSink()
    spec = ToolSpec.model_validate({"mcpServers": {"filesystem": fake_fs_entry(str(tmp_path))}})

    async with McpManager(
        spec, variables={}, masker=SecretMasker(), sink=sink, log_dir=tmp_path / "logs"
    ):
        pass

    assert sink.events == []


def test_default_connect_timeout_is_ten_seconds(tmp_path):
    manager = McpManager(
        ToolSpec(mcp_servers={}),
        variables={},
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
    )

    assert manager.connect_timeout == 10.0
