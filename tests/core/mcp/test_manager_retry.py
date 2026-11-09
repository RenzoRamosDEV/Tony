import asyncio
from types import SimpleNamespace

from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager, ServerStatus


class FakeSession:
    async def list_tools(self):
        tool = SimpleNamespace(name="ping", description="", input_schema={})
        return SimpleNamespace(tools=[tool])


class ScriptedManager(McpManager):
    """Replaces the transport: 'flaky' fails with the scripted outcomes, then connects."""

    def __init__(self, *args, outcomes, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = list(outcomes)
        self.attempts = 0

    async def _connect(self, name, declared, stack):
        self.attempts += 1
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome == "hang":
            await asyncio.sleep(3600)
        if outcome is not None:
            raise RuntimeError(outcome)
        return FakeSession()


class Sleeper:
    def __init__(self):
        self.delays = []
        self.gate = None

    async def __call__(self, delay):
        self.delays.append(delay)
        if self.gate is not None:
            await self.gate.wait()
        await asyncio.sleep(0)


def build(tmp_path, outcomes, sleeper, statuses, **kwargs):
    spec = ToolSpec.model_validate({"mcpServers": {"flaky": {"command": "x"}}})
    return ScriptedManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
        on_status=lambda server, status: statuses.append(status),
        sleep=sleeper,
        outcomes=outcomes,
        **kwargs,
    )


async def settle(manager):
    while manager._retries and not manager.status["flaky"].up:
        await asyncio.sleep(0)
        if all(task.done() for task in manager._retries):
            break
    await asyncio.sleep(0)


async def test_default_retry_delays(tmp_path):
    manager = build(tmp_path, [], Sleeper(), [])

    assert manager.retry_delays == (5.0, 15.0, 30.0)


async def test_fails_once_then_comes_up(tmp_path):
    statuses, sleeper = [], Sleeper()
    sleeper.gate = asyncio.Event()
    manager = build(tmp_path, ["boom"], sleeper, statuses, connect_timeout=1)

    async with manager:
        assert manager.status["flaky"].up is False
        sleeper.gate.set()
        await settle(manager)
        assert manager.status["flaky"] == ServerStatus(up=True)
        assert [tool.id for tool in manager.tools] == ["flaky.ping"]
        assert manager.attempts == 2

    assert [s.up for s in statuses] == [False, True]
    assert sleeper.delays == [5.0]


async def test_always_failing_retries_exactly_n_times_then_stays_down(tmp_path):
    statuses, sleeper = [], Sleeper()
    manager = build(tmp_path, ["e0", "e1", "e2", "e3", "e4"], sleeper, statuses)

    async with manager:
        await settle(manager)
        status = manager.status["flaky"]

    assert manager.attempts == 4
    assert sleeper.delays == [5.0, 15.0, 30.0]
    assert status.up is False and status.reason == "e3"
    assert [s.reason for s in statuses] == ["e0", "e1", "e2", "e3"]


async def test_repeated_identical_failure_is_published_once(tmp_path):
    statuses = []
    manager = build(tmp_path, ["same"] * 4, Sleeper(), statuses)

    async with manager:
        await settle(manager)

    assert [s.reason for s in statuses] == ["same"]


async def test_timeouts_count_as_failures(tmp_path):
    statuses, sleeper = [], Sleeper()
    sleeper.gate = asyncio.Event()
    manager = build(tmp_path, ["hang", None], sleeper, statuses, connect_timeout=0.01)

    async with manager:
        assert manager.status["flaky"].reason == "connect timeout after 0.01 s"
        sleeper.gate.set()
        await settle(manager)
        assert manager.status["flaky"].up is True

    assert sleeper.delays == [5.0]


async def test_shutdown_during_backoff_cancels_the_retry(tmp_path):
    sleeper = Sleeper()
    sleeper.gate = asyncio.Event()
    manager = build(tmp_path, ["boom"], sleeper, [])

    async with manager:
        await asyncio.sleep(0)
        pending = set(manager._retries)
        assert len(pending) == 1

    assert all(task.cancelled() for task in pending)
    assert manager._retries == set()
    assert manager.attempts == 1


async def test_shutdown_after_retry_connected_leaves_no_tasks(tmp_path):
    manager = build(tmp_path, ["boom"], Sleeper(), [])

    async with manager:
        while not manager.status["flaky"].up:
            await asyncio.sleep(0)
        pending = set(manager._retries)

    assert all(task.done() for task in pending)
    assert manager._retries == set()


async def test_up_server_is_never_retried(tmp_path):
    statuses, sleeper = [], Sleeper()
    manager = build(tmp_path, [None], sleeper, statuses)

    async with manager:
        assert manager._retries == set()

    assert manager.attempts == 1 and sleeper.delays == []
    assert [s.up for s in statuses] == [True]


async def test_empty_delays_disable_retry(tmp_path):
    manager = build(tmp_path, ["boom"], Sleeper(), [], retry_delays=())

    async with manager:
        assert manager._retries == set()

    assert manager.attempts == 1


async def test_retry_does_not_touch_other_servers(tmp_path):
    spec = ToolSpec.model_validate(
        {"mcpServers": {"flaky": {"command": "x"}, "fs": fake_fs_entry(str(tmp_path))}}
    )
    manager = McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path / "logs",
    )

    async with manager:
        assert manager._retries == set() or manager.status["fs"].up
        assert manager.status["fs"].up


async def test_wait_settled_returns_after_recovery(tmp_path):
    statuses = []
    manager = build(tmp_path, ["boom"], Sleeper(), statuses)

    async with manager:
        async with asyncio.timeout(5):
            await manager.wait_settled()
        assert manager.status["flaky"].up is True
        pending = set(manager._retries)

    assert [s.up for s in statuses] == [False, True]
    assert all(task.done() for task in pending)


async def test_wait_settled_returns_after_exhaustion(tmp_path):
    sleeper = Sleeper()
    manager = build(tmp_path, ["e0", "e1", "e2", "e3"], sleeper, [])

    async with manager:
        async with asyncio.timeout(5):
            await manager.wait_settled()
        assert manager.status["flaky"].up is False

    assert sleeper.delays == [5.0, 15.0, 30.0]


async def test_wait_settled_returns_at_once_without_failures(tmp_path):
    manager = build(tmp_path, [None], Sleeper(), [])

    async with manager:
        async with asyncio.timeout(1):
            await manager.wait_settled()


async def test_wait_settled_waits_while_backoff_is_pending(tmp_path):
    sleeper = Sleeper()
    sleeper.gate = asyncio.Event()
    manager = build(tmp_path, ["boom"], sleeper, [])

    async with manager:
        waiter = asyncio.create_task(manager.wait_settled())
        await asyncio.sleep(0.01)
        assert not waiter.done()
        sleeper.gate.set()
        async with asyncio.timeout(5):
            await waiter
