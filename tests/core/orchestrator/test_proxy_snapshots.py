from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import ALLOW, RecordingGuard
from tests.fakes.journal import FakeRecorder
from tests.fakes.sinks import ListEventSink
from tests.fakes.snapshots import FakeSnapshots
from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling
from tony.core.guard.policy import Limits
from tony.core.orchestrator.ports import ToolReply
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.supervisor import TaskSupervisor

WRITE = "filesystem.write_file"
ARGS = {"path": "a.md", "content": "nuevo"}


def make(snapshots, *, guard=None, reply=None, recorder=None):
    sink, published = ListEventSink(), []
    recorder = recorder or FakeRecorder()
    caller = FakeToolCaller(reply or ToolReply(text="hecho"))
    proxy = ToolProxy(
        task_id="t1",
        agent="viernes",
        guard=guard or RecordingGuard(ALLOW),
        caller=caller,
        sink=sink,
        masker=SecretMasker(),
        supervisor=TaskSupervisor(Limits(), sink),
        publish=published.append,
        journal=recorder,
        snapshots=snapshots,
    )
    return proxy, recorder, published, caller


async def test_keep_runs_after_prepared_and_before_dispatched():
    recorder = FakeRecorder()
    snapshots = FakeSnapshots(recorder)
    proxy, *_ = make(snapshots, recorder=recorder)

    await proxy.call(WRITE, ARGS)

    assert snapshots.kept == [("call-1", WRITE, ARGS)]
    assert snapshots.states_when_kept == [["prepared"]]


async def test_succeeded_detail_is_the_written_digest():
    proxy, recorder, *_ = make(FakeSnapshots())

    await proxy.call(WRITE, ARGS)

    assert recorder.history[-1] == ("call-1", "succeeded", "sha256=fake-nuevo")


async def test_other_tools_are_untouched():
    snapshots = FakeSnapshots()
    proxy, recorder, *_ = make(snapshots)

    await proxy.call("filesystem.read_file", {"path": "a.md"})

    assert snapshots.kept == []
    assert recorder.history[-1] == ("call-1", "succeeded", "")


async def test_failed_write_does_not_record_a_digest():
    proxy, recorder, *_ = make(FakeSnapshots(), reply=ToolReply(text="boom", is_error=True))

    await proxy.call(WRITE, ARGS)

    assert recorder.history[-1] == ("call-1", "failed", "boom")


async def test_failing_keep_still_executes_and_publishes_one_error():
    proxy, _, published, caller = make(FakeSnapshots(fail=True))

    first = await proxy.call(WRITE, ARGS)
    await proxy.call(WRITE, ARGS)

    assert first == ToolReply(text="hecho")
    assert len(caller.calls) == 2
    errors = [event for event in published if event["type"] == "error"]
    assert len(errors) == 1 and errors[0]["source"] == "undo"
    assert "undo dir not writable" in errors[0]["message"]


async def test_denied_call_takes_no_snapshot():
    snapshots = FakeSnapshots()
    proxy, *_ = make(snapshots, guard=RecordingGuard(Ruling(verdict="deny", rule="r")))

    await proxy.call(WRITE, ARGS)

    assert snapshots.kept == []
