import os

import pytest

from tests.fakes.servers import fake_fs_entry
from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager

HOST = {
    "ALLOWED_VAR": "a",
    "SECRET_VAR": "s",
    "USER": "u",
    "SHELL": "/bin/sh",
    "TERM": "xterm",
    "LOGNAME": "u",
    "PATH": os.environ.get("PATH", ""),
    "HOME": os.environ.get("HOME", ""),
}


def manager_for(tmp_path, servers, host=HOST):
    spec = ToolSpec.model_validate({"mcpServers": servers})
    return McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path / "logs",
        host_environ=host,
    )


def isolated_entry(tmp_path, **extra):
    return fake_fs_entry(str(tmp_path), isolation={"env_allow": ["ALLOWED_VAR"]}, **extra)


async def env_of(manager, name, server="fs"):
    reply = await manager.call(f"{server}.echo_env", {"name": name})
    return reply.text


async def test_allowlisted_and_declared_variables_are_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_VAR", "leak")
    entry = isolated_entry(tmp_path, env={"DECLARED": "d"})
    async with manager_for(tmp_path, {"fs": entry}) as manager:
        assert await env_of(manager, "ALLOWED_VAR") == "a"
        assert await env_of(manager, "DECLARED") == "d"


@pytest.mark.parametrize("name", ["SECRET_VAR", "USER", "SHELL", "TERM", "LOGNAME"])
async def test_non_allowed_variables_are_absent(tmp_path, monkeypatch, name):
    monkeypatch.setenv("SECRET_VAR", "leak")
    async with manager_for(tmp_path, {"fs": isolated_entry(tmp_path)}) as manager:
        assert await env_of(manager, name) == ""


async def test_without_isolation_sdk_defaults_remain(tmp_path):
    async with manager_for(tmp_path, {"fs": fake_fs_entry(str(tmp_path))}) as manager:
        assert await env_of(manager, "PATH") != ""
        assert await env_of(manager, "USER") == os.environ.get("USER", "")


async def test_isolated_server_tools_are_cataloged(tmp_path):
    async with manager_for(tmp_path, {"fs": isolated_entry(tmp_path)}) as manager:
        assert "fs.echo_env" in {tool.id for tool in manager.tools}


async def test_nonexistent_command_is_down_while_other_server_stays_up(tmp_path):
    servers = {
        "broken": {"command": "no-such-command-xyz", "isolation": {}},
        "fs": isolated_entry(tmp_path),
    }
    async with manager_for(tmp_path, servers) as manager:
        assert manager.status["broken"].up is False
        assert manager.status["broken"].reason
        assert manager.status["fs"].up is True
