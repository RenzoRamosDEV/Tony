import json
import shutil
import socket
import subprocess

import pytest

from tests.core.orchestrator.viernes_home import REPO
from tony.core.diagnostics.checks import Check, run_checks
from tony.core.voice.engines.loader import REQUIRED_MODULES

SPEC = object()


def build_home(tmp_path, servers=None):
    home = tmp_path / "home"
    for agent in ("jarvis", "viernes", "edith"):
        shutil.copytree(REPO / "agents" / agent, home / "agents" / agent)
    (home / "agents" / "viernes" / "tool" / "tool.json").write_text(
        json.dumps({"mcpServers": servers or {}})
    )
    return home


def run(home, *, found=("npx",), modules=REQUIRED_MODULES, environ=None):
    return run_checks(
        home,
        which=lambda name: f"/bin/{name}" if name in found else None,
        find_spec=lambda name: SPEC if name in modules else None,
        environ=environ or {},
    )


def row(checks, name):
    [found] = [check for check in checks if check.name == name]
    return found


def statuses(checks):
    return {check.name: check.status for check in checks}


def test_valid_definitions_are_all_ok(tmp_path):
    checks = run(build_home(tmp_path))

    definitions = [check for check in checks if check.name.startswith("definitions:")]
    assert {check.name for check in definitions} >= {
        "definitions:agents/jarvis/agent.md",
        "definitions:agents/viernes/agent.md",
        "definitions:agents/viernes/tool/tool.json",
        "definitions:agents/edith/agent.md",
        "definitions:agents/edith/policy.yaml",
    }
    assert {check.status for check in definitions} == {"ok"}


def test_missing_tony_yaml_is_fine_because_defaults_apply(tmp_path):
    checks = run(build_home(tmp_path))

    assert row(checks, "definitions:config/tony.yaml").status == "ok"


def test_invalid_tony_yaml_fails_and_other_checks_still_run(tmp_path):
    home = build_home(tmp_path)
    (home / "config").mkdir()
    (home / "config" / "tony.yaml").write_text("front: [unclosed\n")

    checks = run(home)

    broken = row(checks, "definitions:config/tony.yaml")
    assert broken.status == "fail" and "config/tony.yaml" in broken.hint
    assert row(checks, "definitions:agents/edith/policy.yaml").status == "ok"


def test_broken_tool_json_fails_naming_the_file_and_the_rest_still_runs(tmp_path):
    home = build_home(tmp_path)
    (home / "agents" / "viernes" / "tool" / "tool.json").write_text("{not json")

    checks = run(home)

    broken = row(checks, "definitions:agents/viernes/tool/tool.json")
    assert broken.status == "fail"
    assert "agents/viernes/tool/tool.json" in broken.hint
    assert row(checks, "definitions:agents/jarvis/agent.md").status == "ok"
    assert row(checks, "definitions:agents/edith/policy.yaml").status == "ok"


def test_broken_agent_md_and_policy_yaml_fail_independently(tmp_path):
    home = build_home(tmp_path)
    (home / "agents" / "jarvis" / "agent.md").write_text("no frontmatter")
    (home / "agents" / "edith" / "policy.yaml").write_text("- not a mapping\n")

    checks = run(home)

    assert row(checks, "definitions:agents/jarvis/agent.md").status == "fail"
    assert row(checks, "definitions:agents/edith/policy.yaml").status == "fail"
    assert row(checks, "definitions:agents/viernes/agent.md").status == "ok"


def test_subagent_definitions_are_checked(tmp_path):
    home = build_home(tmp_path)
    sub = home / "agents" / "viernes" / "subagents" / "x"
    sub.mkdir(parents=True)
    (sub / "agent.md").write_text("broken")

    checks = run(home)

    assert row(checks, "definitions:agents/viernes/subagents/x/agent.md").status == "fail"


def test_a_policy_file_in_a_subagent_folder_is_not_checked(tmp_path):
    home = build_home(tmp_path)
    sub = home / "agents" / "viernes" / "subagents" / "x"
    sub.mkdir(parents=True)
    (sub / "policy.yaml").write_text("- junk\n")

    names = {check.name for check in run(home)}

    assert not [name for name in names if name.endswith("x/policy.yaml")]


def test_hints_are_single_lines(tmp_path):
    home = build_home(tmp_path)
    (home / "config").mkdir()
    (home / "config" / "tony.yaml").write_text("front: [unclosed\nother: 1\n")

    checks = run(home)

    assert row(checks, "definitions:config/tony.yaml").status == "fail"
    assert all("\n" not in check.hint for check in checks)


def test_stdio_command_missing_fails_found_is_ok(tmp_path):
    home = build_home(tmp_path, {"obsidian": {"command": "npx", "args": ["-y", "x"]}})

    missing = run(home, found=())
    present = run(home, found=("npx",))

    assert row(missing, "mcp:viernes/obsidian").status == "fail"
    assert "npx" in row(missing, "mcp:viernes/obsidian").hint
    assert row(present, "mcp:viernes/obsidian").status == "ok"


@pytest.mark.parametrize("declared", ["python", "python3"])
def test_bare_python_is_found_regardless_of_path(tmp_path, declared):
    home = build_home(tmp_path, {"local": {"command": declared, "args": ["-m", "x"]}})

    assert row(run(home, found=()), "mcp:viernes/local").status == "ok"


def test_other_python_names_need_to_be_on_the_path(tmp_path):
    home = build_home(tmp_path, {"local": {"command": "python3.12"}})

    assert row(run(home, found=()), "mcp:viernes/local").status == "fail"


@pytest.mark.parametrize(
    ("url", "status"),
    [
        ("http://host/mcp", "ok"),
        ("https://host/mcp", "ok"),
        ("ftp://host/mcp", "fail"),
        ("host/mcp", "fail"),
    ],
)
def test_http_server_needs_an_http_or_https_scheme(tmp_path, url, status):
    home = build_home(tmp_path, {"remote": {"url": url}})

    assert row(run(home), "mcp:viernes/remote").status == status


def test_undefined_placeholder_fails_naming_the_variable_only(tmp_path):
    home = build_home(
        tmp_path,
        {"gmail": {"command": "npx", "env": {"T": "${GMAIL_TOKEN}"}, "args": ["${HOMEDIR}/x"]}},
    )

    checks = run(home, environ={"HOMEDIR": "/home/u"})

    undefined = row(checks, "vars:viernes/gmail")
    assert undefined.status == "fail"
    assert "GMAIL_TOKEN" in undefined.hint and "HOMEDIR" not in undefined.hint


def test_placeholders_in_url_and_headers_are_checked(tmp_path):
    home = build_home(
        tmp_path,
        {"remote": {"url": "https://${HOST}/mcp", "headers": {"Authorization": "${API_KEY}"}}},
    )

    checks = run(home, environ={})

    hint = row(checks, "vars:viernes/remote").hint
    assert "HOST" in hint and "API_KEY" in hint


def test_variables_from_the_env_file_resolve(tmp_path):
    home = build_home(tmp_path, {"gmail": {"command": "npx", "env": {"T": "${GMAIL_TOKEN}"}}})
    (home / "config").mkdir()
    (home / "config" / ".env").write_text("GMAIL_TOKEN=abc\n")

    assert row(run(home), "vars:viernes/gmail").status == "ok"


def test_variable_values_are_never_printed(tmp_path):
    home = build_home(
        tmp_path,
        {"api": {"command": "npx", "env": {"K": "${API_KEY}", "U": "${MISSING}"}}},
    )

    checks = run(home, environ={"API_KEY": "s3cret"})

    rendered = " ".join(f"{c.name} {c.status} {c.hint}" for c in checks)
    assert "s3cret" not in rendered and "MISSING" in rendered


def test_servers_without_placeholders_are_ok(tmp_path):
    home = build_home(tmp_path, {"plain": {"command": "npx"}})

    assert row(run(home), "vars:viernes/plain").status == "ok"


def test_voice_modules_missing_is_a_warning_naming_them_and_the_install_hint(tmp_path):
    checks = run(build_home(tmp_path), modules=("numpy",))

    voice = row(checks, "voice")
    assert voice.status == "warn"
    assert "torch" in voice.hint and "numpy" not in voice.hint
    assert "uv sync --extra voice" in voice.hint


def test_voice_modules_present_is_ok(tmp_path):
    assert row(run(build_home(tmp_path)), "voice").status == "ok"


def test_music_tools_are_checked_only_when_a_music_server_is_declared(tmp_path):
    plain = run(build_home(tmp_path, {"plain": {"command": "npx"}}), found=("npx",))
    music = run(
        build_home(tmp_path / "m", {"music": {"command": "python", "args": ["-m", "x"]}}),
        found=(),
    )

    assert not {"yt-dlp", "mpv"} & {check.name for check in plain}
    assert (row(music, "yt-dlp").status, row(music, "mpv").status) == ("warn", "warn")


def test_music_tools_found_are_ok(tmp_path):
    home = build_home(tmp_path, {"music": {"command": "python"}})

    checks = run(home, found=("yt-dlp", "mpv"))

    assert (row(checks, "yt-dlp").status, row(checks, "mpv").status) == ("ok", "ok")


def test_checks_spawn_no_process_and_open_no_socket(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("doctor must not run processes or open sockets")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    home = build_home(
        tmp_path,
        {"a": {"command": "npx"}, "b": {"url": "https://host/mcp"}, "music": {"command": "python"}},
    )

    assert run(home)


def test_every_check_is_a_check(tmp_path):
    assert all(isinstance(check, Check) for check in run(build_home(tmp_path)))


def isolated(allow):
    return {"gh": {"command": "npx", "isolation": {"env_allow": allow}}}


def test_missing_allowlisted_variable_warns_naming_server_and_variable(tmp_path):
    home = build_home(tmp_path, isolated(["GITHUB_TOKEN"]))

    found = row(run(home), "isolation:viernes/gh")

    assert found.status == "warn"
    assert "GITHUB_TOKEN" in found.hint


def test_several_missing_variables_give_one_sorted_row(tmp_path):
    home = build_home(tmp_path, isolated(["B_VAR", "A_VAR", "SET_VAR"]))

    found = row(run(home, environ={"SET_VAR": "1"}), "isolation:viernes/gh")

    assert found.hint == "env_allow variables not set in the host: A_VAR, B_VAR"


@pytest.mark.parametrize("allow", [["A"], [], None])
def test_no_isolation_row_when_nothing_is_missing(tmp_path, allow):
    server = {"command": "npx"} if allow is None else isolated(allow)["gh"]
    home = build_home(tmp_path, {"gh": server})

    names = [check.name for check in run(home, environ={"A": "1"})]

    assert "isolation:viernes/gh" not in names
