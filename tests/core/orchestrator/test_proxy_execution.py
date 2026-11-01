import json

import pytest

from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import RecordingGuard
from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.logging.task_log import JsonlTaskLog
from tony.core.mcp.manager import McpManager
from tony.core.orchestrator.ports import ToolReply
from tony.core.orchestrator.proxy import ToolProxy


class RaisingCaller:
    async def call(self, tool_id, args):
        raise RuntimeError("connection lost")


def proxy_for(caller, sink, masker, timeout=20.0):
    return ToolProxy(
        task_id="t1",
        agent="viernes",
        guard=RecordingGuard("allow"),
        caller=caller,
        sink=sink,
        masker=masker,
        timeout=timeout,
    )


def fs_manager(tmp_path, masker, sink):
    spec = ToolSpec.model_validate(
        {"mcpServers": {"fs": fake_fs_entry(str(tmp_path), env={"TOKEN": "${GITHUB_TOKEN}"})}}
    )
    return McpManager(
        spec,
        variables={"GITHUB_TOKEN": "s3cr3t"},
        masker=masker,
        sink=sink,
        log_dir=tmp_path / "logs" / "mcp",
    )


async def test_tool_timeout_returns_error_and_task_continues(tmp_path):
    masker, sink = SecretMasker(), ListEventSink()
    async with fs_manager(tmp_path, masker, sink) as manager:
        proxy = proxy_for(manager, sink, masker, timeout=0.3)

        slow = await proxy.call("fs.sleep", {"seconds": 5})
        after = await proxy.call("fs.list_directory", {"path": "."})

    assert slow.is_error is True
    assert "fs.sleep" in slow.text and "timed out" in slow.text and "0.3" in slow.text
    assert after.is_error is False


async def test_exception_becomes_error_reply():
    sink = ListEventSink()
    proxy = proxy_for(RaisingCaller(), sink, SecretMasker())

    reply = await proxy.call("fs.read_file", {})

    assert reply.is_error is True
    assert "fs.read_file" in reply.text and "connection lost" in reply.text
    assert sink.types() == ["tool_call", "tool_result"]


async def test_secret_is_masked_in_reply_and_log(tmp_path):
    masker = SecretMasker()
    log = JsonlTaskLog(tmp_path, "t1", masker=masker)
    async with fs_manager(tmp_path, masker, log) as manager:
        proxy = proxy_for(manager, log, masker)

        reply = await proxy.call("fs.echo_env", {"name": "TOKEN"})

    assert reply.text == "***"
    lines = [json.loads(line) for line in log.path.read_text().splitlines()]
    result = next(line for line in lines if line["type"] == "tool_result")
    assert result["content"] == "***"
    assert "s3cr3t" not in log.path.read_text()


async def test_secret_is_masked_even_with_list_sink():
    sink = ListEventSink()
    proxy = proxy_for(FakeToolCaller(ToolReply(text="tok=s3cr3t")), sink, SecretMasker({"s3cr3t"}))

    reply = await proxy.call("x.y", {})

    assert reply.text == "tok=***"
    assert sink.events[-1]["content"] == "tok=***"


def test_default_tool_timeout_is_twenty_seconds():
    proxy = ToolProxy(
        task_id="t",
        agent="a",
        guard=RecordingGuard(),
        caller=RaisingCaller(),
        sink=ListEventSink(),
        masker=SecretMasker(),
    )

    assert proxy.timeout == pytest.approx(20.0)
