import asyncio

import pytest

from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import ALLOW, RecordingGuard
from tests.fakes.journal import FakeRecorder
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling
from tony.core.guard.audit import args_hash
from tony.core.guard.policy import Limits
from tony.core.orchestrator.ports import ToolReply
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.supervisor import TaskSupervisor


class RaisingCaller:
    async def call(self, tool_id, args):
        raise RuntimeError("connection lost")


class HangingCaller:
    async def call(self, tool_id, args):
        await asyncio.Event().wait()


class StatesSeenByCaller:
    """Caller recording the journal state at the moment the tool runs."""

    def __init__(self, recorder):
        self._recorder = recorder
        self.seen = None

    async def call(self, tool_id, args):
        self.seen = self._recorder.states()
        return ToolReply(text="ok")


class MutatingGuard(RecordingGuard):
    def __init__(self, args):
        super().__init__(ALLOW)
        self._args = args

    async def decide(self, call):
        self._args["x"] = 2
        return await super().decide(call)


def make(caller=None, guard=None, recorder=None, **limits):
    sink, published = ListEventSink(), []
    recorder = recorder if recorder is not None else FakeRecorder()
    proxy = ToolProxy(
        task_id="t1",
        agent="viernes",
        guard=guard or RecordingGuard(),
        caller=caller or FakeToolCaller(ToolReply(text="hecho")),
        sink=sink,
        masker=SecretMasker(),
        supervisor=TaskSupervisor(Limits(**limits), sink),
        publish=published.append,
        journal=recorder,
    )
    return proxy, recorder, published


async def test_success_path_records_prepared_dispatched_succeeded():
    proxy, recorder, _ = make()

    await proxy.call("gmail.send_email", {"to": "a"})

    assert recorder.states() == ["prepared", "dispatched", "succeeded"]
    assert recorder.rows["call-1"] == {
        "task_id": "t1",
        "agent": "viernes",
        "tool": "gmail.send_email",
        "args_digest": args_hash({"to": "a"}),
    }


async def test_dispatched_is_recorded_before_the_tool_runs():
    recorder = FakeRecorder()
    caller = StatesSeenByCaller(recorder)
    proxy, _, _ = make(caller=caller, recorder=recorder)

    await proxy.call("fs.read_file", {})

    assert caller.seen == ["prepared", "dispatched"]


async def test_error_reply_is_failed_with_the_error_text():
    proxy, recorder, _ = make(caller=FakeToolCaller(ToolReply(text="no such file", is_error=True)))

    await proxy.call("fs.read_file", {})

    assert recorder.history[-1] == ("call-1", "failed", "no such file")


async def test_exception_is_failed():
    proxy, recorder, _ = make(caller=RaisingCaller())

    await proxy.call("fs.read_file", {})

    [*_, (_, state, detail)] = recorder.history
    assert state == "failed" and "connection lost" in detail


async def test_timeout_is_outcome_unknown():
    proxy, recorder, _ = make(caller=HangingCaller(), tool_timeout_s=0.05)

    reply = await proxy.call("fs.read_file", {})

    assert reply.is_error is True
    assert recorder.history[-1] == ("call-1", "outcome_unknown", "timed out after 0.05 s")


async def test_cancellation_leaves_the_row_dispatched():
    proxy, recorder, _ = make(caller=HangingCaller(), tool_timeout_s=30)
    running = asyncio.create_task(proxy.call("fs.read_file", {}))
    await asyncio.sleep(0.01)

    running.cancel()
    await asyncio.gather(running, return_exceptions=True)

    assert recorder.states() == ["prepared", "dispatched"]


@pytest.mark.parametrize(
    "ruling",
    [
        Ruling(verdict="deny", rule="r"),
        Ruling(verdict="confirm", rule="r", user_decision="deny"),
        Ruling(verdict="confirm", rule="r", user_decision="timeout"),
    ],
)
async def test_calls_that_do_not_run_are_not_journaled(ruling):
    proxy, recorder, _ = make(guard=RecordingGuard(ruling))

    await proxy.call("shell.run", {})

    assert recorder.history == []


async def test_confirmed_call_is_journaled():
    proxy, recorder, _ = make(
        guard=RecordingGuard(Ruling(verdict="confirm", rule="r", user_decision="allow"))
    )

    await proxy.call("gmail.send_email", {})

    assert recorder.states() == ["prepared", "dispatched", "succeeded"]


async def test_arguments_changed_call_is_not_journaled():
    args = {"x": 1}
    proxy, recorder, _ = make(guard=MutatingGuard(args))

    await proxy.call("gmail.send_email", args)

    assert recorder.history == []


async def test_a_failing_journal_does_not_block_the_call_and_reports_once():
    caller = FakeToolCaller(ToolReply(text="hecho"))
    proxy, _, published = make(caller=caller, recorder=FakeRecorder(fail=True))

    first = await proxy.call("fs.read_file", {})
    second = await proxy.call("fs.read_file", {})

    assert (first.text, second.text) == ("hecho", "hecho")
    assert len(caller.calls) == 2
    errors = [event for event in published if event["type"] == "error"]
    assert len(errors) == 1 and errors[0]["source"] == "journal"
    assert "disk full" in errors[0]["message"]


async def test_run_subagent_is_journaled_without_a_timeout():
    proxy, recorder, _ = make()

    await proxy.call("tony.run_subagent", {"name": "resumidor"})

    assert recorder.states() == ["prepared", "dispatched", "succeeded"]
    assert recorder.rows["call-1"]["tool"] == "tony.run_subagent"


async def test_without_a_journal_calls_run_as_before():
    sink = ListEventSink()
    proxy = ToolProxy(
        task_id="t1",
        agent="viernes",
        guard=RecordingGuard(),
        caller=FakeToolCaller(ToolReply(text="hecho")),
        sink=sink,
        masker=SecretMasker(),
        supervisor=TaskSupervisor(Limits(), sink),
    )

    assert (await proxy.call("fs.read_file", {})).text == "hecho"
