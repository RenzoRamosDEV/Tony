import asyncio
import json

import pytest

from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import ALLOW, RecordingGuard
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling, ToolCall
from tony.core.guard.policy import Limits
from tony.core.mcp.manager import CatalogTool
from tony.core.orchestrator.ports import ToolReply
from tony.core.orchestrator.proxy import ToolProxy, cap_text
from tony.core.orchestrator.supervisor import TaskSupervisor

CONTENT = ToolReply(text="contenido")
DENY = Ruling(verdict="deny", rule="shell.run/deny")


def make_proxy(ruling=ALLOW, reply=CONTENT, caller=None, **limits):
    guard, sink = RecordingGuard(ruling), ListEventSink()
    caller = caller or FakeToolCaller(reply)
    supervisor = TaskSupervisor(Limits(**limits), sink)
    proxy = ToolProxy(
        task_id="abc",
        agent="viernes",
        guard=guard,
        caller=caller,
        sink=sink,
        masker=SecretMasker(),
        supervisor=supervisor,
    )
    return proxy, guard, caller, sink, supervisor


async def test_guard_receives_exact_envelope():
    proxy, guard, *_ = make_proxy()

    await proxy.call("filesystem.read_file", {"path": "a.md"})

    assert guard.calls == [
        ToolCall(task_id="abc", agent="viernes", tool="filesystem.read_file", args={"path": "a.md"})
    ]


async def test_allow_executes_and_returns_reply():
    proxy, _, caller, *_ = make_proxy(ALLOW)

    reply = await proxy.call("filesystem.read_file", {"path": "a.md"})

    assert caller.calls == [("filesystem.read_file", {"path": "a.md"})]
    assert reply == ToolReply(text="contenido")


async def test_deny_returns_blocked_by_policy_without_executing():
    proxy, _, caller, _, supervisor = make_proxy(DENY)

    reply = await proxy.call("shell.run", {"command": "sudo x"})

    assert caller.calls == []
    assert reply == ToolReply(
        text='{"error": "blocked_by_policy", "rule": "shell.run/deny"}', is_error=True
    )
    assert json.loads(reply.text) == {"error": "blocked_by_policy", "rule": "shell.run/deny"}
    assert not supervisor.cancelled.is_set()


async def test_repeated_denials_reach_the_supervisor():
    proxy, _, _, _, supervisor = make_proxy(DENY)

    for _ in range(3):
        await proxy.call("shell.run", {})

    assert supervisor.reason == (
        "tarea cancelada: shell.run bloqueada 3 veces por la política (regla shell.run/deny)"
    )


async def test_confirmed_call_executes():
    confirmed = Ruling(verdict="confirm", rule="fs.delete*/confirm", user_decision="allow")
    proxy, _, caller, _, supervisor = make_proxy(confirmed)

    reply = await proxy.call("fs.delete_file", {"path": "a.md"})

    assert reply == CONTENT
    assert caller.calls == [("fs.delete_file", {"path": "a.md"})]
    assert not supervisor.cancelled.is_set()


@pytest.mark.parametrize(
    ("user_decision", "reason_part"),
    [("deny", "no autorizó"), ("timeout", "sin respuesta"), (None, "no autorizó")],
)
async def test_unconfirmed_call_is_not_executed_and_cancels(user_decision, reason_part):
    ruling = Ruling(verdict="confirm", rule="fs.delete*/confirm", user_decision=user_decision)
    proxy, _, caller, _, supervisor = make_proxy(ruling)

    reply = await proxy.call("fs.delete_file", {"path": "a.md"})

    assert caller.calls == []
    assert reply == ToolReply(
        text="tool fs.delete_file was not executed: "
        f"not confirmed by the user ({user_decision or 'deny'})",
        is_error=True,
    )
    assert supervisor.cancelled.is_set() and reason_part in supervisor.reason


async def test_step_overflow_skips_the_guard_and_cancels():
    proxy, guard, caller, sink, supervisor = make_proxy(max_steps_per_agent=1)

    await proxy.call("fs.read_file", {})
    reply = await proxy.call("fs.read_file", {})

    assert len(guard.calls) == 1 and len(caller.calls) == 1
    assert reply == ToolReply(
        text="tool fs.read_file was not executed: "
        "tarea cancelada: viernes superó el límite de 1 pasos",
        is_error=True,
    )
    assert supervisor.reason == "tarea cancelada: viernes superó el límite de 1 pasos"
    assert sink.types() == ["tool_call", "tool_result", "tool_call", "tool_result"]


class SlowCaller:
    def __init__(self, seconds):
        self.seconds = seconds
        self.calls = []

    async def call(self, tool_id, args):
        self.calls.append(tool_id)
        await asyncio.sleep(self.seconds)
        return CONTENT


async def test_tool_timeout_from_policy_limits():
    proxy, *_ = make_proxy(caller=SlowCaller(1), tool_timeout_s=0.05)

    reply = await proxy.call("fs.sleep", {})

    assert reply == ToolReply(text="tool fs.sleep timed out after 0.05 s", is_error=True)


async def test_tool_timeout_counted_after_confirmation():
    class SlowConfirmGuard:
        async def decide(self, call):
            await asyncio.sleep(0.2)
            return Ruling(verdict="confirm", rule="r", user_decision="allow")

    sink = ListEventSink()
    proxy = ToolProxy(
        task_id="abc",
        agent="viernes",
        guard=SlowConfirmGuard(),
        caller=SlowCaller(0.05),
        sink=sink,
        masker=SecretMasker(),
        supervisor=TaskSupervisor(Limits(tool_timeout_s=0.15), sink),
    )

    assert await proxy.call("fs.delete_file", {}) == CONTENT


async def test_logs_call_then_result_in_order():
    proxy, _, _, sink, _ = make_proxy()

    await proxy.call("fs.read_file", {"path": "a.md"})

    assert sink.events == [
        {"type": "tool_call", "agent": "viernes", "tool": "fs.read_file", "args": {"path": "a.md"}},
        {
            "type": "tool_result",
            "agent": "viernes",
            "tool": "fs.read_file",
            "ok": True,
            "content": "contenido",
        },
    ]


async def test_error_reply_is_logged_as_not_ok():
    proxy, _, _, sink, _ = make_proxy(reply=ToolReply(text="no such file", is_error=True))

    reply = await proxy.call("fs.read_file", {})

    assert reply == ToolReply(text="no such file", is_error=True)
    assert sink.events[-1]["ok"] is False


async def test_denied_call_is_logged_with_error_result():
    proxy, _, _, sink, _ = make_proxy(DENY)

    reply = await proxy.call("shell.run", {})

    assert sink.types() == ["tool_call", "tool_result"]
    assert sink.events[-1] == {
        "type": "tool_result",
        "agent": "viernes",
        "tool": "shell.run",
        "ok": False,
        "content": reply.text,
    }


async def test_wraps_catalog_tools_as_proxied_tools():
    proxy, guard, caller, *_ = make_proxy()
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


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("abcd", 5, "abcd"),
        ("abcde", 5, "abcde"),
        ("abcdef", 5, "abcde\n[truncated: showing first 5 of 6 characters]"),
        ("abcdef", 0, "abcdef"),
        ("", 5, ""),
    ],
)
def test_cap_text_boundaries(text, limit, expected):
    assert cap_text(text, limit) == expected


async def test_large_result_is_capped_for_the_model_but_logged_in_full():
    full = "x" * 50
    proxy, _, _, sink, _ = make_proxy(reply=ToolReply(text=full), tool_result_max_chars=20)

    reply = await proxy.call("filesystem.read_file", {})

    assert reply == ToolReply(text="x" * 20 + "\n[truncated: showing first 20 of 50 characters]")
    logged = [e for e in sink.events if e["type"] == "tool_result"]
    assert logged[0]["content"] == full


async def test_result_at_the_limit_is_unchanged():
    proxy, *_ = make_proxy(reply=ToolReply(text="y" * 20), tool_result_max_chars=20)

    reply = await proxy.call("filesystem.read_file", {})

    assert reply.text == "y" * 20


async def test_error_result_is_never_capped():
    error = ToolReply(text="e" * 50, is_error=True)
    proxy, *_ = make_proxy(reply=error, tool_result_max_chars=20)

    reply = await proxy.call("filesystem.read_file", {})

    assert reply == error


async def test_cap_disabled_returns_everything():
    proxy, *_ = make_proxy(reply=ToolReply(text="z" * 50), tool_result_max_chars=0)

    reply = await proxy.call("filesystem.read_file", {})

    assert reply.text == "z" * 50


async def test_cap_applies_after_masking():
    sink, supervisor = (
        ListEventSink(),
        TaskSupervisor(Limits(tool_result_max_chars=8), ListEventSink()),
    )
    proxy = ToolProxy(
        task_id="abc",
        agent="viernes",
        guard=RecordingGuard(ALLOW),
        caller=FakeToolCaller(ToolReply(text="s3cr3t-and-more")),
        sink=sink,
        masker=SecretMasker({"s3cr3t"}),
        supervisor=supervisor,
    )

    reply = await proxy.call("filesystem.read_file", {})

    assert reply.text == "***-and-" + "\n[truncated: showing first 8 of 12 characters]"


class MutatingGuard(RecordingGuard):
    """Guard that alters the caller's arguments while it deliberates, as a late edit would."""

    def __init__(self, args, ruling=ALLOW) -> None:
        super().__init__(ruling)
        self._args = args

    async def decide(self, call):
        self._args["path"] = "/etc/passwd"
        return await super().decide(call)


def proxy_with_guard(guard):
    sink, caller = ListEventSink(), FakeToolCaller(CONTENT)
    supervisor = TaskSupervisor(Limits(), sink)
    proxy = ToolProxy(
        task_id="abc",
        agent="viernes",
        guard=guard,
        caller=caller,
        sink=sink,
        masker=SecretMasker(),
        supervisor=supervisor,
    )
    return proxy, caller, supervisor


async def test_arguments_changed_after_the_ruling_are_not_executed():
    args = {"path": "a.md"}
    proxy, caller, supervisor = proxy_with_guard(MutatingGuard(args))

    reply = await proxy.call("filesystem.write_file", args)

    assert reply.is_error is True
    assert reply.text == (
        "tool filesystem.write_file was not executed: not confirmed by the user (arguments changed)"
    )
    assert caller.calls == []
    assert supervisor.cancelled.is_set()


async def test_arguments_changed_cancel_the_task_as_unconfirmed():
    args = {"path": "a.md"}
    proxy, _, supervisor = proxy_with_guard(
        MutatingGuard(args, Ruling(verdict="confirm", rule="r", user_decision="allow"))
    )

    await proxy.call("filesystem.write_file", args)

    assert "r" in supervisor.reason and "filesystem.write_file" in supervisor.reason


async def test_unchanged_arguments_execute():
    args = {"path": "a.md"}
    proxy, caller, _ = proxy_with_guard(RecordingGuard())

    reply = await proxy.call("filesystem.read_file", args)

    assert reply == CONTENT
    assert caller.calls == [("filesystem.read_file", {"path": "a.md"})]


async def test_denied_call_with_mutated_arguments_still_reports_the_policy_block():
    args = {"path": "a.md"}
    proxy, caller, _ = proxy_with_guard(MutatingGuard(args, DENY))

    reply = await proxy.call("shell.run", args)

    assert json.loads(reply.text) == {"error": "blocked_by_policy", "rule": "shell.run/deny"}
    assert caller.calls == []
