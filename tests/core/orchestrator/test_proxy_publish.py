import pytest

from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import RecordingGuard
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling
from tony.core.guard.audit import args_preview
from tony.core.guard.policy import Limits
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.supervisor import TaskSupervisor

MASKER = SecretMasker({"s3cr3t"})
ARGS = {"command": "echo s3cr3t", "api_key": "k3y"}


def make_proxy(ruling, **limits):
    published, sink = [], ListEventSink()
    proxy = ToolProxy(
        task_id="t1",
        agent="viernes",
        guard=RecordingGuard(ruling),
        caller=FakeToolCaller(),
        sink=sink,
        masker=MASKER,
        supervisor=TaskSupervisor(Limits(**limits), sink),
        publish=published.append,
    )
    return proxy, published, sink


@pytest.mark.parametrize(
    "ruling",
    [
        Ruling(verdict="allow", rule="shell.*/allow"),
        Ruling(verdict="deny", rule="shell.run/deny"),
        Ruling(verdict="confirm", rule="shell.run/confirm", user_decision="deny"),
        Ruling(verdict="confirm", rule="shell.run/confirm", user_decision="allow"),
    ],
    ids=["allow", "deny", "confirm-deny", "confirm-allow"],
)
async def test_tool_call_event_published_after_the_ruling(ruling):
    proxy, published, _ = make_proxy(ruling)

    await proxy.call("shell.run", ARGS)

    [event] = published
    assert {key: value for key, value in event.items() if key != "ts"} == {
        "type": "tool_call",
        "task_id": "t1",
        "agent": "viernes",
        "tool": "shell.run",
        "args_preview": args_preview(ARGS, MASKER),
        **ruling.model_dump(),
    }
    assert "s3cr3t" not in event["args_preview"] and "k3y" not in event["args_preview"]


async def test_deny_event_has_null_user_decision():
    proxy, published, _ = make_proxy(Ruling(verdict="deny", rule="shell.run/deny"))

    await proxy.call("shell.run", {"command": "sudo dnf update"})

    assert (published[0]["verdict"], published[0]["rule"], published[0]["user_decision"]) == (
        "deny",
        "shell.run/deny",
        None,
    )


async def test_no_event_when_the_step_limit_stops_the_call_before_judging():
    proxy, published, _ = make_proxy(Ruling(verdict="allow", rule="r"), max_steps_per_agent=1)

    await proxy.call("shell.run", {})
    await proxy.call("shell.run", {})

    assert len(published) == 1


async def test_task_log_events_unchanged():
    proxy, _, sink = make_proxy(Ruling(verdict="allow", rule="r"))

    await proxy.call("shell.run", {"command": "ls"})

    assert sink.types() == ["tool_call", "tool_result"]
