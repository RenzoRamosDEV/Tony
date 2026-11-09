import json
import sys

import pytest

from tony.core.loader.tool_json import McpServer
from tony.core.mcp.isolation import isolated_environment, isolated_parameters

HOST = {
    "PATH": "/bin",
    "HOME": "/home/u",
    "LANG": "C",
    "LC_ALL": "C.UTF-8",
    "GITHUB_TOKEN": "t",
    "SECRET_X": "1",
    "USER": "u",
    "SHELL": "/bin/sh",
}


def compose(allow=(), env=None, host=HOST):
    server = McpServer(command="x", env=env or {}, isolation={"env_allow": list(allow)})
    return isolated_environment(server, host)


def test_allowlisted_set_variable_is_copied():
    assert compose(["GITHUB_TOKEN"])["GITHUB_TOKEN"] == "t"


def test_allowlisted_unset_variable_is_skipped():
    assert "MISSING" not in compose(["MISSING"])


def test_empty_isolation_yields_only_base_set():
    assert compose() == {"PATH": "/bin", "HOME": "/home/u", "LANG": "C", "LC_ALL": "C.UTF-8"}


@pytest.mark.parametrize("name", ["PATH", "HOME", "LANG", "LC_ALL"])
def test_base_variable_is_skipped_when_unset(name):
    host = {key: value for key, value in HOST.items() if key != name}

    assert name not in compose(host=host)


@pytest.mark.parametrize("name", ["SECRET_X", "USER", "SHELL"])
def test_non_allowed_host_variable_is_absent(name):
    assert name not in compose(["GITHUB_TOKEN"])


def test_declared_env_is_added():
    assert compose(env={"API_KEY": "k"})["API_KEY"] == "k"


def test_declared_env_overrides_host_value():
    assert compose(["GITHUB_TOKEN"], {"GITHUB_TOKEN": "declared"})["GITHUB_TOKEN"] == "declared"


def test_declared_env_overrides_base_value():
    assert compose(env={"PATH": "/opt"})["PATH"] == "/opt"


def test_launch_parameters_run_the_launcher_without_values_in_argv():
    server = McpServer(command="npx", args=["-y", "pkg"], env={"API_KEY": "k-secret"}, isolation={})

    params = isolated_parameters("npx", server, HOST)

    assert params.command == sys.executable
    assert params.args[0] == "-I"
    assert params.args[2:] == ["npx", "-y", "pkg"]
    assert "k-secret" not in " ".join(params.args)
    assert json.loads(params.env["TONY_ISOLATED_ENV"])["API_KEY"] == "k-secret"
    assert list(params.env) == ["TONY_ISOLATED_ENV"]
