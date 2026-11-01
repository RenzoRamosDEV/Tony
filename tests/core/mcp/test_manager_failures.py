import asyncio
import sys

import pytest

from tests.fakes.processes import processes_mentioning
from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager, _describe

HANGING = {"command": sys.executable, "args": ["-c", "import time; time.sleep(30)"]}


def manager_for(tmp_path, broken, sink, variables=None, timeout=10.0):
    spec = ToolSpec.model_validate(
        {"mcpServers": {"broken": broken, "filesystem": fake_fs_entry(str(tmp_path))}}
    )
    return McpManager(
        spec,
        variables=secret_variables(variables or {}),
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
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=sink,
        log_dir=tmp_path / "logs",
    ):
        pass

    assert sink.events == []


def test_default_connect_timeout_is_ten_seconds(tmp_path):
    manager = McpManager(
        ToolSpec(mcp_servers={}),
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
    )

    assert manager.connect_timeout == 10.0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ExceptionGroup("g", [FileNotFoundError("no cmd"), ValueError("other")]), "no cmd"),
        (ExceptionGroup("g", [ExceptionGroup("inner", [OSError("deep")])]), "deep"),
        (RuntimeError(), "RuntimeError"),
        (TimeoutError(), "connect timeout after 2.5 s"),
    ],
)
def test_describe_reports_the_root_cause(error, expected):
    assert _describe(error, 2.5) == expected


async def test_cancel_while_connecting_closes_the_server_process(tmp_path):
    marker = f"tony-cancel-marker-{tmp_path.name}"
    hanging = {**HANGING, "args": [*HANGING["args"], marker]}
    spec = ToolSpec.model_validate({"mcpServers": {"slow": hanging}})
    manager = McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path / "logs",
    )

    async def enter():
        async with manager:
            pass

    entering = asyncio.create_task(enter())
    while not processes_mentioning(marker):
        await asyncio.sleep(0.02)
    entering.cancel()
    await asyncio.gather(entering, return_exceptions=True)

    assert entering.cancelled()
    assert processes_mentioning(marker) == []
