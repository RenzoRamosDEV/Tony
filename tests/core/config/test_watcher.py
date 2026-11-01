import asyncio

import pytest
from watchfiles import Change

from tony.core.config.watcher import config_filter, watch_config


@pytest.mark.parametrize(
    ("relative", "accepted"),
    [
        ("agents/x/tool/tool.json", True),
        ("agents/x/subagents/y/tool/tool.json", True),
        ("agents/edith/policy.yaml", True),
        ("agents/x/tool/tool.json.lock", False),
        ("agents/x/tool/tool.json.tmp", False),
        ("agents/x/policy.yaml", False),
        ("agents/x/agent.md", False),
        ("agents/x/skills/s/SKILL.md", False),
    ],
)
def test_filter(tmp_path, relative, accepted):
    accept = config_filter(tmp_path, "edith")

    assert accept(Change.modified, str(tmp_path / relative)) is accepted


async def test_real_watcher_yields_written_tool_json_and_stops(tmp_path):
    tool = tmp_path / "agents" / "viernes" / "tool"
    tool.mkdir(parents=True)
    stop = asyncio.Event()
    batches = []

    async def consume():
        async for batch in watch_config(tmp_path, "edith", stop, debounce=50, step=10):
            batches.append(batch)
            stop.set()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.2)
    (tool / "tool.json.lock").write_text("")
    (tool / "tool.json").write_text("{}")
    async with asyncio.timeout(5):
        await task

    assert batches == [{tmp_path / "agents" / "viernes" / "tool" / "tool.json"}]
