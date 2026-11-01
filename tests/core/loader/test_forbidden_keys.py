import json

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.loader.tool_json import parse_tool_spec

FILE = "agents/viernes/tool/tool.json"
POLICY = "agents/edith/policy.yaml"


def parse(data):
    return parse_tool_spec(json.dumps(data), file=FILE, native_tools=set())


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"mcpServers": {}, "confirm": ["filesystem.write_file"]}, "confirm"),
        ({"mcpServers": {}, "allow": []}, "allow"),
        (
            {"mcpServers": {"filesystem": {"command": "npx", "allow": ["read_file"]}}},
            "mcpServers.filesystem.allow",
        ),
        (
            {"mcpServers": {"fs": {"command": "npx", "env": {"confirm": "x"}}}},
            "mcpServers.fs.env.confirm",
        ),
        ({"mcpServers": {"allow": {"command": "npx"}}}, "mcpServers.allow"),
        (
            {"mcpServers": {"fs": {"command": "npx", "args": ["a", {"confirm": 1}]}}},
            "mcpServers.fs.args.1.confirm",
        ),
    ],
)
def test_permission_key_rejected_with_dotted_path(data, field):
    with pytest.raises(DefinitionError) as info:
        parse(data)

    assert (info.value.file, info.value.field) == (FILE, field)
    assert POLICY in str(info.value)


def test_permission_word_as_value_is_allowed():
    spec = parse({"mcpServers": {"fs": {"command": "npx", "args": ["allow", "confirm"]}}})

    assert spec.mcp_servers["fs"].args == ["allow", "confirm"]


@pytest.mark.parametrize("key", ["Allow", "allowed", "confirmations"])
def test_similar_keys_are_not_permission_keys(key):
    with pytest.raises(DefinitionError) as info:
        parse({"mcpServers": {}, key: []})

    assert POLICY not in str(info.value)
