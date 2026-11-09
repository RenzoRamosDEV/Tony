import asyncio
import threading
import time

import pytest

from tests.core.orchestrator.test_runtime import Harness, home_for
from tests.core.orchestrator.test_runtime_voice import ready, with_voice
from tony.core.voice.engines.devices import DeviceInfo


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


class SlowQuery:
    """A blocking device query that waits for `release`; counts the calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self):
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        return ()


@pytest.fixture
def query(monkeypatch):
    slow = SlowQuery()
    monkeypatch.setattr("tony.core.orchestrator.runtime.list_devices", slow)
    yield slow
    slow.release.set()


async def test_slow_discovery_does_not_block_the_loop(tmp_path, query):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        await asyncio.to_thread(query.started.wait, 5)
        ticks, last_gap = 0, 0.0
        previous = time.monotonic()
        while ticks < 10:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            last_gap, previous, ticks = max(last_gap, now - previous), now, ticks + 1
        assert harness.of("audio_devices") == []
        query.release.set()
        await harness.until(lambda: harness.of("audio_devices"))

    assert last_gap < 0.1


async def test_concurrent_requests_share_one_query(tmp_path, query):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        await asyncio.to_thread(query.started.wait, 5)
        harness.send(type="list_devices")
        await asyncio.sleep(0.05)
        query.release.set()
        await harness.wait_for("audio_devices", 2)

    first, second = harness.of("audio_devices")
    assert query.calls == 1
    assert (first["input"], first["output"]) == (second["input"], second["output"])


async def test_a_request_after_completion_runs_a_new_query(tmp_path, query):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()
    query.release.set()

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        await harness.wait_for("audio_devices", 1)
        harness.send(type="list_devices")
        await harness.wait_for("audio_devices", 2)

    assert query.calls == 2


async def test_late_result_after_shutdown_is_not_published(tmp_path, query):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        await asyncio.to_thread(query.started.wait, 5)

    query.release.set()
    await asyncio.sleep(0.1)

    assert harness.of("audio_devices") == []
    assert all(task.done() for task in asyncio.all_tasks() if task is not asyncio.current_task())


async def test_a_failing_query_is_published_as_an_error(tmp_path, monkeypatch):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()

    def broken():
        raise OSError("pw-dump roto")

    monkeypatch.setattr("tony.core.orchestrator.runtime.list_devices", broken)

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        await harness.until(lambda: harness.of("error"))

    assert "pw-dump roto" in harness.of("error")[-1]["message"]


async def test_devices_are_split_by_kind(tmp_path, monkeypatch):
    home, _ = home_for(tmp_path)
    _, voice = with_voice()
    mic = DeviceInfo("Mic", "input", False)
    speaker = DeviceInfo("Altavoz", "output", True)
    monkeypatch.setattr("tony.core.orchestrator.runtime.list_devices", lambda: (mic, speaker))

    async with Harness(home, voice=voice) as harness:
        await ready(harness)
        harness.send(type="list_devices")
        event = (await harness.wait_for("audio_devices"))[-1]

    assert [device["name"] for device in event["input"]] == ["Mic"]
    assert [device["name"] for device in event["output"]] == ["Altavoz"]
