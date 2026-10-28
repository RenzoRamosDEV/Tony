"""ConfigWatcher: only tool/tool.json changes, one reload per agent per batch."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from tests.fakes.fake_watch import ScriptedWatch
from tony.core.config.watcher import ConfigWatcher, agent_of, is_tool_json

MODIFIED = 2
ADDED = 1


class Recorder:
    def __init__(self) -> None:
        self.agents: list[str] = []
        self.seen = asyncio.Event()

    async def __call__(self, agent: str) -> None:
        self.agents.append(agent)
        self.seen.set()


def test_is_tool_json_accepts_only_tool_json_under_a_tool_folder() -> None:
    assert is_tool_json(MODIFIED, "/r/agents/viernes/tool/tool.json") is True
    assert is_tool_json(ADDED, "/r/agents/viernes/subagents/x/tool/tool.json") is True
    assert is_tool_json(MODIFIED, "/r/agents/viernes/agent.md") is False
    assert is_tool_json(MODIFIED, "/r/agents/viernes/tool/tool.json.bak") is False
    assert is_tool_json(MODIFIED, "/r/agents/viernes/tool.json") is False


def test_agent_of_is_the_first_folder_under_agents_dir() -> None:
    agents = Path("/r/agents")

    assert agent_of(agents, "/r/agents/viernes/tool/tool.json") == "viernes"
    assert agent_of(agents, "/r/agents/viernes/subagents/investigador/tool/tool.json") == "viernes"
    assert agent_of(agents, "/elsewhere/tool/tool.json") is None
    assert agent_of(agents, "/r/agents") is None


async def run_watcher(batches: list[set], tmp_path: Path) -> list[str]:
    watch, recorder = ScriptedWatch(), Recorder()
    agents = tmp_path / "agents"
    watcher = ConfigWatcher(agents, recorder, watch=watch)
    watcher.start()
    for batch in batches:
        watch.feed({(kind, str(agents / rel)) for kind, rel in batch})
    await asyncio.sleep(0.02)
    await watcher.stop()
    assert watch.calls[0]["paths"] == (agents,)
    return recorder.agents


async def test_tool_json_change_reloads_its_agent(tmp_path: Path) -> None:
    assert await run_watcher([{(MODIFIED, "viernes/tool/tool.json")}], tmp_path) == ["viernes"]


async def test_subagent_tool_json_reloads_the_parent(tmp_path: Path) -> None:
    batches = [{(ADDED, "viernes/subagents/investigador/tool/tool.json")}]

    assert await run_watcher(batches, tmp_path) == ["viernes"]


async def test_other_files_are_ignored(tmp_path: Path) -> None:
    batches = [{(MODIFIED, "viernes/agent.md"), (MODIFIED, "jarvis/skills/x/SKILL.md")}]

    assert await run_watcher(batches, tmp_path) == []


async def test_changes_of_the_same_agent_in_one_batch_reload_once(tmp_path: Path) -> None:
    batches = [
        {
            (MODIFIED, "viernes/tool/tool.json"),
            (ADDED, "viernes/subagents/investigador/tool/tool.json"),
            (MODIFIED, "jarvis/tool/tool.json"),
        }
    ]

    assert await run_watcher(batches, tmp_path) == ["jarvis", "viernes"]


async def test_a_failing_reload_does_not_stop_the_watcher(tmp_path: Path) -> None:
    watch = ScriptedWatch()
    calls: list[str] = []

    async def flaky(agent: str) -> None:
        calls.append(agent)
        raise RuntimeError("boom")

    watcher = ConfigWatcher(tmp_path, flaky, watch=watch)
    watcher.start()
    watch.feed({(MODIFIED, str(tmp_path / "a/tool/tool.json"))})
    await asyncio.sleep(0.01)
    watch.feed({(MODIFIED, str(tmp_path / "b/tool/tool.json"))})
    await asyncio.sleep(0.01)
    await watcher.stop()

    assert calls == ["a", "b"]


async def test_stop_ends_the_task_quickly_and_is_idempotent(tmp_path: Path) -> None:
    watcher = ConfigWatcher(tmp_path, Recorder(), watch=ScriptedWatch())
    watcher.start()
    await asyncio.sleep(0)
    started = time.monotonic()

    await watcher.stop()
    await watcher.stop()

    assert time.monotonic() - started < 1
    assert watcher.running is False


async def test_real_watchfiles_sees_a_tool_json_write(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    (agents / "viernes" / "tool").mkdir(parents=True)
    recorder = Recorder()
    watcher = ConfigWatcher(agents, recorder, debounce_ms=50)
    watcher.start()
    await asyncio.sleep(0.3)
    try:
        (agents / "viernes" / "tool" / "tool.json").write_text(
            json.dumps({"native": []}), encoding="utf-8"
        )
        await asyncio.wait_for(recorder.seen.wait(), 5)
    finally:
        await watcher.stop()

    assert recorder.agents == ["viernes"]


async def test_running_flag_and_stop_before_start(tmp_path: Path) -> None:
    watcher = ConfigWatcher(tmp_path, Recorder(), watch=ScriptedWatch())
    assert watcher.running is False

    await watcher.stop()
    watcher.start()
    assert watcher.running is True
    await watcher.stop()

    assert watcher.running is False
    assert agent_of(tmp_path, str(tmp_path / "viernes")) is None
