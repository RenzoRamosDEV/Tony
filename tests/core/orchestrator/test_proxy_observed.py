import asyncio

from tests.fakes.callers import FakeToolCaller
from tests.fakes.guards import ALLOW, RecordingGuard
from tests.fakes.sinks import ListEventSink
from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling
from tony.core.evidence.observed import ObservedTexts
from tony.core.guard.policy import Limits
from tony.core.orchestrator.ports import ToolReply
from tony.core.orchestrator.proxy import ToolProxy
from tony.core.orchestrator.supervisor import TaskSupervisor


class ChangingGuard:
    """Allows the call but rewrites its arguments while it is being judged."""

    def __init__(self, args):
        self.args = args

    async def decide(self, call):
        self.args["path"] = "otro"
        return ALLOW


class SlowCaller:
    def __init__(self, seconds):
        self.seconds = seconds

    async def call(self, tool_id, args):
        await asyncio.sleep(self.seconds)
        return ToolReply(text="respuesta")


def make(reply=None, *, ruling=ALLOW, caller=None, guard=None, observed=True, **limits):
    sink = ListEventSink()
    record = ObservedTexts() if observed else None
    proxy = ToolProxy(
        task_id="abc",
        agent="viernes",
        guard=guard or RecordingGuard(ruling),
        caller=caller or FakeToolCaller(reply or ToolReply(text="contenido")),
        sink=sink,
        masker=SecretMasker(["s3cret"]),
        supervisor=TaskSupervisor(Limits(**limits), sink),
        observed=record,
    )
    return proxy, record


async def test_successful_mcp_result_is_recorded():
    proxy, observed = make()

    await proxy.call("gmail.read", {})

    assert observed.texts() == ("contenido",)


async def test_recorded_text_is_the_masked_text():
    proxy, observed = make(ToolReply(text="clave s3cret"))

    await proxy.call("gmail.read", {})

    assert "s3cret" not in observed.texts()[0]


async def test_recorded_text_is_the_capped_text_with_marker():
    proxy, observed = make(ToolReply(text="x" * 20), tool_result_max_chars=10)

    reply = await proxy.call("gmail.read", {})

    assert observed.texts() == (reply.text,)
    assert observed.texts()[0].startswith("x" * 10 + "\n[truncated")


async def test_error_reply_is_not_recorded():
    proxy, observed = make(ToolReply(text="no such file", is_error=True))

    await proxy.call("gmail.read", {})

    assert observed.texts() == ()


async def test_denied_call_records_nothing():
    proxy, observed = make(ruling=Ruling(verdict="deny", rule="r"))

    await proxy.call("gmail.read", {})

    assert observed.texts() == ()


async def test_unconfirmed_call_records_nothing():
    proxy, observed = make(ruling=Ruling(verdict="confirm", rule="r", user_decision="deny"))

    await proxy.call("gmail.read", {})

    assert observed.texts() == ()


async def test_call_with_changed_arguments_records_nothing():
    args = {"path": "a"}
    proxy, observed = make(guard=ChangingGuard(args))

    await proxy.call("gmail.read", args)

    assert observed.texts() == ()


async def test_native_results_are_not_recorded():
    proxy, observed = make()

    await proxy.call("tony.read_skill", {})
    await proxy.call("tony.ask_user", {})
    await proxy.call("tony.run_subagent", {})

    assert observed.texts() == ()


async def test_tool_whose_name_merely_starts_like_tony_is_recorded():
    proxy, observed = make()

    await proxy.call("tonyx.read", {})

    assert observed.texts() == ("contenido",)


async def test_without_observed_the_proxy_behaves_as_before():
    proxy, observed = make(observed=False)

    reply = await proxy.call("gmail.read", {})

    assert observed is None
    assert reply == ToolReply(text="contenido")


async def test_ask_user_is_not_cut_by_the_tool_timeout():
    proxy, _ = make(caller=SlowCaller(0.1), tool_timeout_s=0.02)

    ask = await proxy.call("tony.ask_user", {})
    other = await proxy.call("gmail.read", {})

    assert ask == ToolReply(text="respuesta")
    assert other.is_error and "timed out" in other.text
