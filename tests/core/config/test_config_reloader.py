import asyncio
import io
import json
import sys
from datetime import UTC, datetime

import pytest

from tests.fakes.processes import processes_mentioning
from tests.fakes.servers import fake_fs_entry
from tony.core.config.reload import (
    ConfigReloader,
    LivePolicy,
    LiveToolSpecs,
    classify,
    diff_servers,
    mcp_probe,
)
from tony.core.guard.policy import load_policy
from tony.core.loader.tool_json import McpServer

POLICY_FILE = "agents/edith/policy.yaml"
TOOL_FILE = "agents/viernes/tool/tool.json"
SUB_FILE = "agents/viernes/subagents/resumidor/tool/tool.json"
FIXED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def server(command="x", **extra):
    return McpServer.model_validate({"command": command, **extra})


def test_diff_servers_partitions():
    old = {"a": server(), "b": server(args=["1"]), "c": server()}
    new = {"a": server(), "b": server(args=["2"]), "d": server("y")}

    diff = diff_servers(old, new)

    assert (diff.added, diff.changed, diff.removed) == (["d"], ["b"], ["c"])


@pytest.mark.parametrize(
    "changed",
    [
        server(env={"A": "1"}),
        server("other"),
        McpServer.model_validate({"url": "http://x"}),
    ],
)
def test_diff_servers_any_field_change(changed):
    assert diff_servers({"a": server()}, {"a": changed}).changed == ["a"]


def test_diff_servers_equivalent_defaults_unchanged():
    diff = diff_servers({"a": server()}, {"a": server(args=[], env={})})

    assert (diff.added, diff.changed, diff.removed) == ([], [], [])


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("agents/viernes/tool/tool.json", ("tools", "viernes")),
        ("agents/viernes/subagents/resumidor/tool/tool.json", ("tools", "viernes/resumidor")),
        ("agents/edith/policy.yaml", ("policy", None)),
        ("agents/viernes/policy.yaml", None),
        ("agents/viernes/tool/tool.json.lock", None),
        ("agents/viernes/tool/tool.json.tmp", None),
        ("agents/viernes/agent.md", None),
        ("agents/viernes/skills/x/SKILL.md", None),
        ("agents/viernes/tool.json", None),
        ("agents/viernes/subagents/r/x/tool/tool.json", None),
        ("agents/viernes/subagents/r/tool/other.json", None),
        ("agents/viernes/other/r/tool/tool.json", None),
        ("other/viernes/subagents/r/tool/tool.json", None),
        ("config/tony.yaml", None),
    ],
)
def test_classify(tmp_path, relative, expected):
    assert classify(tmp_path, "edith", tmp_path / relative) == expected


def test_classify_outside_root(tmp_path):
    assert classify(tmp_path / "home", "edith", tmp_path / "agents/edith/policy.yaml") is None


def write(root, file, text):
    path = root / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class Harness:
    def __init__(self, root, servers):
        write(root, POLICY_FILE, "default: allow\n")
        write(root, TOOL_FILE, json.dumps({"mcpServers": servers}))
        self.root = root
        self.policy = LivePolicy(root, "edith", load_policy(root, "edith"))
        self.tools = LiveToolSpecs(root, native_tools=set())
        assert self.tools.reload("viernes") is None
        self.published = []
        self.stderr = io.StringIO()
        self.probed = []
        self.release = asyncio.Event()
        self.reloader = ConfigReloader(
            root,
            "edith",
            self.policy,
            self.tools,
            publish=self.published.append,
            stderr=self.stderr,
            probe=self.probe,
            clock=lambda: FIXED,
        )

    async def probe(self, key, name, entry):
        self.probed.append((key, name, entry.command))

    async def touch(self, *files):
        await self.reloader.handle({self.root / file for file in files})
        await self.reloader.wait_idle()


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path, {"a": {"command": "x"}, "b": {"command": "y", "args": ["1"]}})


async def test_policy_change_applied_without_event(harness):
    write(harness.root, POLICY_FILE, "default: deny\n")

    await harness.touch(POLICY_FILE)

    assert harness.policy.current().default == "deny"
    assert harness.published == [] and harness.stderr.getvalue() == ""


async def test_invalid_policy_reported_and_previous_kept(harness):
    write(harness.root, POLICY_FILE, "default: [roto\n")

    await harness.touch(POLICY_FILE)

    assert harness.policy.current().default == "allow"
    [event] = harness.published
    assert (event["type"], event["source"], event["ts"]) == ("error", "reload", FIXED.isoformat())
    assert POLICY_FILE in event["message"]
    assert harness.stderr.getvalue().startswith(f"tony: warning: {POLICY_FILE}")


async def test_invalid_tool_json_reported_with_field(harness):
    write(harness.root, TOOL_FILE, json.dumps({"mcpServers": {}, "confirm": []}))

    await harness.touch(TOOL_FILE)

    [event] = harness.published
    assert TOOL_FILE in event["message"] and "confirm" in event["message"]
    assert "confirm" in harness.stderr.getvalue()
    assert list(harness.tools.spec_for("viernes").mcp_servers) == ["a", "b"]
    assert harness.probed == []


async def test_only_changed_server_probed(harness):
    servers = {"a": {"command": "x"}, "b": {"command": "y", "args": ["2"]}}
    write(harness.root, TOOL_FILE, json.dumps({"mcpServers": servers}))

    await harness.touch(TOOL_FILE)

    assert harness.probed == [("viernes", "b", "y")]
    assert harness.published == []


async def test_added_server_probed(harness):
    servers = {"a": {"command": "x"}, "b": {"command": "y", "args": ["1"]}, "c": {"command": "z"}}
    write(harness.root, TOOL_FILE, json.dumps({"mcpServers": servers}))

    await harness.touch(TOOL_FILE)

    assert harness.probed == [("viernes", "c", "z")]


async def test_removed_server_published_down(harness):
    write(harness.root, TOOL_FILE, json.dumps({"mcpServers": {"a": {"command": "x"}}}))

    await harness.touch(TOOL_FILE)

    assert harness.probed == []
    assert [
        (e["type"], e["agent"], e["server"], e["up"], e["reason"], e["ts"])
        for e in harness.published
    ] == [("mcp_status", "viernes", "b", False, "removed from tool.json", FIXED.isoformat())]


async def test_subagent_tool_json_uses_subagent_key(harness):
    write(harness.root, SUB_FILE, json.dumps({"mcpServers": {"s": {"command": "q"}}}))

    await harness.touch(SUB_FILE)

    assert harness.probed == [("viernes/resumidor", "s", "q")]


async def test_unrelated_path_does_not_stop_the_batch(harness):
    write(harness.root, TOOL_FILE, json.dumps({"mcpServers": {"a": {"command": "x"}}}))

    await harness.touch("agents/viernes/agent.md", TOOL_FILE)

    assert [e["server"] for e in harness.published] == ["b"]


async def test_failing_probe_does_not_break_waiting(tmp_path):
    harness = Harness(tmp_path, {})

    async def failing(key, name, entry):
        raise RuntimeError("boom")

    harness.reloader._probe = failing
    write(tmp_path, TOOL_FILE, json.dumps({"mcpServers": {"n": {"command": "x"}}}))

    await harness.touch(TOOL_FILE)


async def test_unrelated_paths_ignored(harness):
    write(harness.root, "agents/viernes/agent.md", "x")

    await harness.touch("agents/viernes/agent.md", "agents/viernes/tool/tool.json.lock")

    assert (harness.probed, harness.published) == ([], [])


async def test_run_consumes_stream_and_stop_cancels_pending_probes(tmp_path):
    harness = Harness(tmp_path, {})
    started, cancelled = asyncio.Event(), []

    async def hanging_probe(key, name, entry):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    harness.reloader = ConfigReloader(
        tmp_path,
        "edith",
        harness.policy,
        harness.tools,
        publish=harness.published.append,
        stderr=harness.stderr,
        probe=hanging_probe,
    )
    write(tmp_path, TOOL_FILE, json.dumps({"mcpServers": {"n": {"command": "x"}}}))

    async def stream():
        yield {tmp_path / TOOL_FILE}
        await asyncio.Event().wait()

    task = asyncio.create_task(harness.reloader.run(stream()))
    async with asyncio.timeout(5):
        await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert cancelled == ["n"]


async def test_real_probe_publishes_status_and_leaves_no_process(tmp_path):
    published = []
    notes = tmp_path / "probe-notes"
    notes.mkdir()
    probe = mcp_probe(
        tmp_path, environ={"NOTES_DIR": str(notes)}, publish=published.append, clock=lambda: FIXED
    )
    entry = McpServer.model_validate(fake_fs_entry("${NOTES_DIR}"))

    async with asyncio.timeout(20):
        await probe("viernes", "notas", entry)

    assert [(e["type"], e["agent"], e["server"], e["up"], e["ts"]) for e in published] == [
        ("mcp_status", "viernes", "notas", True, FIXED.isoformat())
    ]
    assert (tmp_path / "logs" / "mcp" / "notas.log").is_file()
    assert processes_mentioning(str(notes)) == []


async def test_real_probe_of_broken_server_publishes_reason(tmp_path):
    published = []
    probe = mcp_probe(tmp_path, environ={}, publish=published.append, connect_timeout=0.5)
    entry = McpServer.model_validate({"command": "/nonexistent/tony-no-such-cmd"})

    async with asyncio.timeout(20):
        await probe("viernes", "roto", entry)

    [event] = published
    assert event["up"] is False and "tony-no-such-cmd" in event["reason"]


async def test_real_probe_uses_the_connect_timeout(tmp_path):
    published = []
    probe = mcp_probe(tmp_path, environ={}, publish=published.append, connect_timeout=0.2)
    entry = McpServer.model_validate(
        {"command": sys.executable, "args": ["-c", "import time; time.sleep(30)"]}
    )

    async with asyncio.timeout(10):
        await probe("viernes", "lento", entry)

    assert published[0]["reason"] == "connect timeout after 0.2 s"


async def test_default_stderr_is_resolved_when_warning(tmp_path, capsys):
    harness = Harness(tmp_path, {})
    reloader = ConfigReloader(
        tmp_path, "edith", harness.policy, harness.tools, publish=list().append, probe=None
    )
    write(tmp_path, POLICY_FILE, "default: [roto\n")

    await reloader.handle({tmp_path / POLICY_FILE})

    assert capsys.readouterr().err.startswith(f"tony: warning: {POLICY_FILE}")
