import json

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.config.reload import LivePolicy, LiveToolSpecs, StaticPolicy
from tony.core.guard.policy import Policy, load_policy_with_version

POLICY_FILE = "agents/edith/policy.yaml"
TOOL_FILE = "agents/viernes/tool/tool.json"
SUB_FILE = "agents/viernes/subagents/resumidor/tool/tool.json"
NATIVE = {"read_skill", "run_subagent"}


def write(root, file, text):
    path = root / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def live_policy(tmp_path):
    write(tmp_path, POLICY_FILE, "default: allow\n")
    policy, version = load_policy_with_version(tmp_path, "edith")
    return LivePolicy(tmp_path, "edith", policy, version)


def test_live_policy_starts_with_seed(live_policy):
    assert live_policy.current().default == "allow"


def test_valid_policy_replaces(tmp_path, live_policy):
    write(tmp_path, POLICY_FILE, "default: deny\n")

    assert live_policy.reload() is None
    assert live_policy.current().default == "deny"


@pytest.mark.parametrize(
    ("text", "field"),
    [("default: [roto\n", None), ("default: maybe\n", "default"), ("- a\n", None)],
)
def test_invalid_policy_keeps_previous(tmp_path, live_policy, text, field):
    write(tmp_path, POLICY_FILE, text)

    error = live_policy.reload()

    assert isinstance(error, DefinitionError)
    assert (error.file, error.field) == (POLICY_FILE, field)
    assert live_policy.current().default == "allow"


def test_missing_policy_keeps_previous(tmp_path, live_policy):
    (tmp_path / POLICY_FILE).unlink()

    error = live_policy.reload()

    assert error.file == POLICY_FILE
    assert live_policy.current().default == "allow"


def test_policy_recovers_after_fix(tmp_path, live_policy):
    write(tmp_path, POLICY_FILE, "default: [roto\n")
    live_policy.reload()
    write(tmp_path, POLICY_FILE, "default: confirm\n")

    assert live_policy.reload() is None
    assert live_policy.current().default == "confirm"


def tool_json(servers=None, **extra):
    return json.dumps({"mcpServers": servers or {}, **extra})


@pytest.fixture
def specs(tmp_path):
    write(tmp_path, TOOL_FILE, tool_json({"a": {"command": "x"}}))
    return LiveToolSpecs(tmp_path, native_tools=NATIVE)


def test_spec_for_reads_file_when_nothing_cached(specs):
    assert list(specs.spec_for("viernes").mcp_servers) == ["a"]
    assert specs.cached("viernes") is None


def test_spec_for_without_valid_file_raises(tmp_path, specs):
    write(tmp_path, TOOL_FILE, "roto")

    with pytest.raises(DefinitionError):
        specs.spec_for("viernes")


def test_reload_caches_valid_spec(tmp_path, specs):
    assert specs.reload("viernes") is None
    write(tmp_path, TOOL_FILE, "roto")

    assert list(specs.spec_for("viernes").mcp_servers) == ["a"]
    assert list(specs.cached("viernes").mcp_servers) == ["a"]


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("roto", None),
        (tool_json(confirm=[]), "confirm"),
        (tool_json({"a.b": {"command": "x"}}), "mcpServers.a.b"),
        (tool_json(native=["now"]), "native"),
    ],
)
def test_invalid_tool_json_keeps_previous(tmp_path, specs, text, field):
    specs.reload("viernes")
    write(tmp_path, TOOL_FILE, text)

    error = specs.reload("viernes")

    assert (error.file, error.field) == (TOOL_FILE, field)
    assert list(specs.spec_for("viernes").mcp_servers) == ["a"]


def test_missing_tool_json_keeps_previous(tmp_path, specs):
    specs.reload("viernes")
    (tmp_path / TOOL_FILE).unlink()

    assert specs.reload("viernes").file == TOOL_FILE
    assert list(specs.spec_for("viernes").mcp_servers) == ["a"]


def test_tool_json_recovers_after_fix(tmp_path, specs):
    specs.reload("viernes")
    write(tmp_path, TOOL_FILE, "roto")
    specs.reload("viernes")
    write(tmp_path, TOOL_FILE, tool_json({"b": {"command": "y"}}))

    assert specs.reload("viernes") is None
    assert list(specs.spec_for("viernes").mcp_servers) == ["b"]


def test_subagent_key(tmp_path, specs):
    write(tmp_path, SUB_FILE, tool_json({"s": {"command": "x"}}))

    assert specs.reload("viernes/resumidor") is None
    assert list(specs.spec_for("viernes/resumidor").mcp_servers) == ["s"]


def test_static_policy_reports_its_version():
    assert StaticPolicy(Policy(default="allow"), "v1").version() == "v1"


def test_live_policy_version_follows_each_successful_reload(tmp_path, live_policy):
    seed = live_policy.version()
    write(tmp_path, POLICY_FILE, "default: deny\n")

    live_policy.reload()

    assert live_policy.version() not in (seed, "")


def test_failed_reload_keeps_policy_and_version(tmp_path, live_policy):
    seed = live_policy.version()
    write(tmp_path, POLICY_FILE, "default: maybe\n")

    assert live_policy.reload() is not None

    assert live_policy.version() == seed
    assert live_policy.current().default == "allow"
