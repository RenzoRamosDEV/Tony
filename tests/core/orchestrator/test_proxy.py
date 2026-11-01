import pytest

from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import RecordingGuard
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import ToolCall
from tony.core.mcp.manager import CatalogTool
from tony.core.orchestrator.ports import ToolReply
from tony.core.orchestrator.proxy import ToolProxy

CONTENT = ToolReply(text="contenido")


def make_proxy(decision="allow", reply=CONTENT):
    guard, caller, sink = RecordingGuard(decision), FakeToolCaller(reply), ListEventSink()
    proxy = ToolProxy(
        task_id="abc",
        agent="viernes",
        guard=guard,
        caller=caller,
        sink=sink,
        masker=SecretMasker(),
    )
    return proxy, guard, caller, sink


async def test_guard_receives_exact_envelope():
    proxy, guard, _, _ = make_proxy()

    await proxy.call("filesystem.read_file", {"path": "a.md"})

    assert guard.calls == [
        ToolCall(task_id="abc", agent="viernes", tool="filesystem.read_file", args={"path": "a.md"})
    ]


async def test_allow_executes_and_returns_reply():
    proxy, _, caller, _ = make_proxy("allow")

    reply = await proxy.call("filesystem.read_file", {"path": "a.md"})

    assert caller.calls == [("filesystem.read_file", {"path": "a.md"})]
    assert reply == ToolReply(text="contenido")


@pytest.mark.parametrize("decision", ["deny", "confirm"])
async def test_non_allow_does_not_execute_and_names_tool(decision):
    proxy, _, caller, _ = make_proxy(decision)

    reply = await proxy.call("filesystem.write_file", {"path": "a.md"})

    assert caller.calls == []
    assert reply.is_error is True
    assert "filesystem.write_file" in reply.text and decision in reply.text


async def test_logs_call_then_result_in_order():
    proxy, _, _, sink = make_proxy()

    await proxy.call("fs.read_file", {"path": "a.md"})

    assert sink.events == [
        {"type": "tool_call", "tool": "fs.read_file", "args": {"path": "a.md"}},
        {"type": "tool_result", "tool": "fs.read_file", "ok": True, "content": "contenido"},
    ]


async def test_error_reply_is_logged_as_not_ok():
    proxy, _, _, sink = make_proxy(reply=ToolReply(text="no such file", is_error=True))

    reply = await proxy.call("fs.read_file", {})

    assert reply == ToolReply(text="no such file", is_error=True)
    assert sink.events[-1]["ok"] is False


async def test_denied_call_is_logged_with_error_result():
    proxy, _, _, sink = make_proxy("deny")

    reply = await proxy.call("fs.write_file", {})

    assert sink.types() == ["tool_call", "tool_result"]
    assert sink.events[-1] == {
        "type": "tool_result",
        "tool": "fs.write_file",
        "ok": False,
        "content": reply.text,
    }


async def test_wraps_catalog_tools_as_proxied_tools():
    proxy, guard, caller, _ = make_proxy()
    catalog = [CatalogTool("fs.read_file", "fs", "read_file", "Read.", {"type": "object"})]

    [proxied] = proxy.wrap(catalog)
    reply = await proxied.handler({"path": "a.md"})

    assert (proxied.id, proxied.description, proxied.input_schema) == (
        "fs.read_file",
        "Read.",
        {"type": "object"},
    )
    assert reply == ToolReply(text="contenido")
    assert [call.tool for call in guard.calls] == ["fs.read_file"]
    assert caller.calls == [("fs.read_file", {"path": "a.md"})]
