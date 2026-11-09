import json
import subprocess
import sys
import textwrap

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.loader.tool_json_writer import add_server

FILE = "agents/viernes/tool/tool.json"
NATIVE = {"read_skill", "run_subagent"}
ORIGINAL = (
    '{\n  "mcpServers": {\n    "filesystem": {"command": "npx", "args": ["-y"]},\n'
    '    "zeta": {"url": "http://z"}\n  },\n  "native": ["read_skill"]\n}\n'
)
WORKER_MD = "---\nname: {name}\nrole: {role}\n---\nPrompt.\n"


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / "agents" / "viernes"
    (folder / "tool").mkdir(parents=True)
    (folder / "agent.md").write_text(WORKER_MD.format(name="viernes", role="worker"))
    (folder / "tool" / "tool.json").write_text(ORIGINAL)
    edith = tmp_path / "agents" / "edith"
    edith.mkdir()
    (edith / "agent.md").write_text(WORKER_MD.format(name="edith", role="guard"))
    return tmp_path


def add(home, name="notas", entry=None, key="viernes", **options):
    return add_server(home, key, name, entry or {"command": "uvx"}, native_tools=NATIVE, **options)


def text(home, file=FILE):
    return (home / file).read_text()


def test_entry_appended_keeping_order_and_native(home):
    written = add(home, entry={"command": "npx", "args": ["${HOME}/notas"], "env": {"LOG": "1"}})

    data = json.loads(text(home))
    assert written == FILE
    assert list(data) == ["mcpServers", "native"]
    assert list(data["mcpServers"]) == ["filesystem", "zeta", "notas"]
    assert data["mcpServers"]["notas"] == {
        "command": "npx",
        "args": ["${HOME}/notas"],
        "env": {"LOG": "1"},
    }
    assert data["native"] == ["read_skill"]


def test_format_two_space_utf8_trailing_newline(home):
    add(home, entry={"command": "eco", "args": ["canción"]})

    raw = (home / FILE).read_bytes().decode("utf-8")
    assert raw.endswith("}\n") and not raw.endswith("\n\n")
    assert '\n  "mcpServers": {\n    "filesystem"' in raw
    assert "canción" in raw


@pytest.mark.parametrize(
    ("name", "entry", "field"),
    [
        ("filesystem", None, "mcpServers.filesystem"),
        ("tony", None, "mcpServers.tony"),
        ("a.b", None, "mcpServers.a.b"),
        ("x", {"command": "a", "url": "http://b"}, "mcpServers.x"),
    ],
)
def test_refused_names_and_entries_leave_file_identical(home, name, entry, field):
    with pytest.raises(DefinitionError) as info:
        add(home, name, entry)

    assert (info.value.file, info.value.field) == (FILE, field)
    assert name in str(info.value)
    assert text(home) == ORIGINAL
    assert sorted(path.name for path in (home / "agents/viernes/tool").iterdir()) == [
        "tool.json",
        "tool.json.lock",
    ]


def test_guard_refused_without_creating_tool_folder(home):
    with pytest.raises(DefinitionError) as info:
        add(home, key="edith")

    assert (info.value.file, info.value.message) == ("agents/edith/", "a guard agent has no tools")
    assert not (home / "agents/edith/tool").exists()


def test_missing_agent_names_folder(home):
    with pytest.raises(DefinitionError) as info:
        add(home, key="nadie")

    assert str(info.value) == "agents/nadie/: agent folder agents/nadie/ does not exist"


def test_missing_tool_json_names_path(home):
    (home / FILE).unlink()

    with pytest.raises(DefinitionError) as info:
        add(home)

    assert str(info.value) == f"{FILE}: missing file {FILE}"
    assert not (home / FILE).exists()


def test_subagent_target(home):
    sub = home / "agents/viernes/subagents/resumidor"
    (sub / "tool").mkdir(parents=True)
    (sub / "agent.md").write_text(WORKER_MD.format(name="resumidor", role="worker"))
    (sub / "tool/tool.json").write_text('{"mcpServers": {}}\n')

    assert add(home, key="viernes/resumidor") == (
        "agents/viernes/subagents/resumidor/tool/tool.json"
    )
    assert json.loads((sub / "tool/tool.json").read_text())["mcpServers"] == {
        "notas": {"command": "uvx"}
    }


HOLD_LOCK = textwrap.dedent(
    """
    import fcntl, sys, time
    handle = open(sys.argv[1], "a")
    fcntl.flock(handle, fcntl.LOCK_EX)
    print("locked", flush=True)
    time.sleep(10)
    """
)


def test_lock_held_elsewhere_times_out_naming_lock_file(home):
    lock = home / "agents/viernes/tool/tool.json.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(lock)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(DefinitionError) as info:
            add(home, lock_timeout=0.2)
    finally:
        holder.kill()
        holder.wait()

    assert info.value.file == "agents/viernes/tool/tool.json.lock"
    assert text(home) == ORIGINAL


WRITER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from tony.core.loader.tool_json_writer import add_server
    add_server(Path(sys.argv[1]), "viernes", sys.argv[2], {"command": "x"},
               native_tools={"read_skill"})
    """
)


def test_concurrent_writers_both_kept(home):
    writers = [
        subprocess.Popen([sys.executable, "-c", WRITER, str(home), name]) for name in ("a", "b")
    ]
    assert [writer.wait(timeout=20) for writer in writers] == [0, 0]

    servers = json.loads(text(home))["mcpServers"]
    assert {"a", "b"} <= set(servers)


def test_failing_replace_leaves_original(home, monkeypatch):
    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr("tony.core.loader.tool_json_writer.os.replace", broken)

    with pytest.raises(OSError):
        add(home)

    assert text(home) == ORIGINAL
    assert not (home / "agents/viernes/tool/tool.json.tmp").exists()


@pytest.mark.parametrize("broken", ["roto", "[]"])
def test_invalid_existing_file_names_it_and_is_unchanged(home, broken):
    (home / FILE).write_text(broken)

    with pytest.raises(DefinitionError) as info:
        add(home)

    assert info.value.file == FILE
    assert text(home) == broken


def test_duplicate_message_names_server_and_file(home):
    with pytest.raises(DefinitionError) as info:
        add(home, "filesystem")

    assert info.value.message == f"server 'filesystem' already exists in {FILE}"


def test_file_without_servers_key_gets_one(home):
    (home / FILE).write_text("{}")

    add(home)

    assert json.loads(text(home)) == {"mcpServers": {"notas": {"command": "uvx"}}}


@pytest.mark.parametrize("agent_md", [None, "sin frontmatter"])
def test_folder_without_readable_role_is_not_a_guard(home, agent_md):
    md = home / "agents/viernes/agent.md"
    if agent_md is None:
        md.unlink()
    else:
        md.write_text(agent_md)

    assert add(home) == FILE


def test_entry_with_isolation_is_written(home):
    entry = {"command": "uvx", "isolation": {"env_allow": ["GITHUB_TOKEN"]}}

    add(home, entry=entry)

    assert json.loads(text(home))["mcpServers"]["notas"] == entry


def test_invalid_isolation_is_refused_and_file_untouched(home):
    with pytest.raises(DefinitionError):
        add(home, entry={"command": "uvx", "isolation": {"env_allow": ["1BAD"]}})

    assert text(home) == ORIGINAL
