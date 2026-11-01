import json

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.loader.tool_json import load_tool_spec

FILE = "agents/viernes/tool/tool.json"
NATIVE = {"now"}

STDIO = {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/notas"],
}
HTTP = {"url": "https://example.test/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}


def write(root, content):
    folder = root / "agents" / "viernes" / "tool"
    folder.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    (folder / "tool.json").write_text(text)


def load(root):
    return load_tool_spec(root, "viernes", native_tools=NATIVE)


def error_of(root, content):
    write(root, content)
    with pytest.raises(DefinitionError) as info:
        load(root)
    assert info.value.file == FILE
    return info.value


def test_stdio_and_http_servers_accepted(tmp_path):
    write(tmp_path, {"mcpServers": {"filesystem": STDIO, "remote": HTTP}})

    spec = load(tmp_path)

    fs, remote = spec.mcp_servers["filesystem"], spec.mcp_servers["remote"]
    assert (fs.command, fs.args, fs.env, fs.url) == ("npx", STDIO["args"], {}, None)
    assert (remote.url, remote.headers, remote.command) == (HTTP["url"], HTTP["headers"], None)
    assert spec.native == []


def test_stdio_defaults(tmp_path):
    write(tmp_path, {"mcpServers": {"s": {"command": "srv"}}})

    server = load(tmp_path).mcp_servers["s"]

    assert (server.args, server.env, server.is_stdio) == ([], {}, True)


def test_http_is_not_stdio(tmp_path):
    write(tmp_path, {"mcpServers": {"r": {"url": "http://x"}}})

    server = load(tmp_path).mcp_servers["r"]

    assert (server.headers, server.is_stdio) == ({}, False)


def test_empty_server_map_accepted(tmp_path):
    write(tmp_path, {"mcpServers": {}})

    assert load(tmp_path).mcp_servers == {}


@pytest.mark.parametrize(
    "entry",
    [
        {"command": "npx", "url": "https://x"},
        {},
        {"args": ["x"]},
        {"url": "https://x", "args": ["a"]},
        {"url": "https://x", "env": {"A": "b"}},
        {"command": "npx", "headers": {"A": "b"}},
    ],
)
def test_invalid_transport_combination_names_server(tmp_path, entry):
    error = error_of(tmp_path, {"mcpServers": {"filesystem": entry}})

    assert error.field == "mcpServers.filesystem"


def test_unknown_server_key(tmp_path):
    error = error_of(tmp_path, {"mcpServers": {"fs": {"command": "x", "cwd": "/"}}})

    assert error.field == "mcpServers.fs.cwd"


def test_unknown_top_level_key(tmp_path):
    error = error_of(tmp_path, {"mcpServers": {}, "skills": []})

    assert error.field == "skills"


def test_missing_mcp_servers(tmp_path):
    assert error_of(tmp_path, {"native": []}).field == "mcpServers"


@pytest.mark.parametrize("text", ["{not json", "", "[1, 2]", "null"])
def test_invalid_json_names_file(tmp_path, text):
    error_of(tmp_path, text)


def test_missing_file_names_expected_path(tmp_path):
    with pytest.raises(DefinitionError) as info:
        load(tmp_path)

    assert info.value.file == FILE
    assert FILE in str(info.value)


def test_reserved_server_name(tmp_path):
    error = error_of(tmp_path, {"mcpServers": {"tony": STDIO}})

    assert error.field == "mcpServers.tony"


def test_known_native_tool_accepted(tmp_path):
    write(tmp_path, {"mcpServers": {}, "native": ["now"]})

    assert load(tmp_path).native == ["now"]


@pytest.mark.parametrize("native", [["clock"], ["now", "clock"]])
def test_unknown_native_tool(tmp_path, native):
    error = error_of(tmp_path, {"mcpServers": {}, "native": native})

    assert error.field == "native"
    assert "clock" in error.message


@pytest.mark.parametrize("name", ["brave_search", "gh-1", "a", "A1", "a_b-c9"])
def test_server_names_accepted(tmp_path, name):
    write(tmp_path, {"mcpServers": {name: {"command": "srv"}}})

    assert list(load(tmp_path).mcp_servers) == [name]


@pytest.mark.parametrize(
    "name", ["my.server", "my__server", "-x", "x-", "a--b", "", "_a", "a_", "a b", "a-_b"]
)
def test_server_names_rejected(tmp_path, name):
    error = error_of(tmp_path, {"mcpServers": {name: {"command": "srv"}}})

    assert error.field == f"mcpServers.{name}"
    assert "server name" in error.message
