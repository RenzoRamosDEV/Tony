import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tony.apps.cli.main import create_app
from tony.core.guard.allow_always import insert_allow_always

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "home"
    shutil.copytree(REPO / "agents" / "edith", root / "agents" / "edith")
    return root


def policy(home, *args):
    return CliRunner().invoke(create_app(), ["policy", *args], env={"TONY_HOME": str(home)})


def policy_bytes(home):
    return (home / "agents" / "edith" / "policy.yaml").read_bytes()


def test_explain_shows_verdict_rule_and_one_based_position(home):
    result = policy(home, "explain", "filesystem.read_file")

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "verdict: allow",
        "rule: filesystem.read_*/allow",
        "position: 2",
    ]


def test_explain_uses_args(home):
    result = policy(home, "explain", "shell.run", "--args", '{"cmd": "sudo rm -rf /"}')

    assert "verdict: deny" in result.stdout


def test_explain_default_prints_no_position(home):
    result = policy(home, "explain", "nothing.matches")

    assert result.exit_code == 0
    assert "rule: default" in result.stdout and "position" not in result.stdout


@pytest.mark.parametrize("bad", ["[1]", "not json", '"text"'])
def test_explain_rejects_bad_args_with_exit_2(home, bad):
    before = policy_bytes(home)

    result = policy(home, "explain", "shell.run", "--args", bad)

    assert result.exit_code == 2 and result.stderr.startswith("tony:")
    assert policy_bytes(home) == before


def test_explain_does_not_modify_the_policy(home):
    before = policy_bytes(home)

    policy(home, "explain", "shell.run")

    assert policy_bytes(home) == before


def test_grants_lists_tool_ids_and_none_message(home):
    insert_allow_always(home, "edith", "fs.write")
    insert_allow_always(home, "edith", "fs.read")
    result = policy(home, "grants")

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "fs.read",
        "fs.write",
        "google-calendar.manage-accounts",
    ]


def test_grants_without_any_prints_the_no_grants_message(home):
    policy(home, "revoke", "google-calendar.manage-accounts")

    result = policy(home, "grants")

    assert result.exit_code == 0 and result.stdout.strip() == "no allow-always grants"


def test_revoke_removes_the_grant(home):
    insert_allow_always(home, "edith", "fs.write")

    result = policy(home, "revoke", "fs.write")

    assert result.exit_code == 0 and "fs.write" in result.stdout
    assert "fs.write" not in policy(home, "grants").stdout


def test_revoke_unknown_grant_exits_1_and_leaves_the_file(home):
    before = policy_bytes(home)

    result = policy(home, "revoke", "fs.write")

    assert result.exit_code == 1 and "fs.write" in result.stderr
    assert policy_bytes(home) == before


def test_revoke_of_a_shipped_rule_exits_1(home):
    before = policy_bytes(home)

    assert policy(home, "revoke", "shell.run").exit_code == 1
    assert policy_bytes(home) == before


def write_cases(home, items):
    path = home / "cases.json"
    path.write_text(json.dumps(items))
    return str(path)


def test_simulate_all_pass_exits_0(home):
    path = write_cases(home, [{"tool": "filesystem.read_file", "args": {}, "expect": "allow"}])

    result = policy(home, "simulate", path)

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["pass 1 filesystem.read_file"]


def test_simulate_failure_shows_the_actual_verdict_and_exits_1(home):
    path = write_cases(
        home,
        [
            {"tool": "filesystem.read_file", "expect": "allow"},
            {"tool": "shell.run", "args": {"cmd": "ls"}, "expect": "allow"},
        ],
    )

    result = policy(home, "simulate", path)

    assert result.exit_code == 1
    assert result.stdout.splitlines() == [
        "pass 1 filesystem.read_file",
        "fail 2 shell.run: expected allow, got confirm",
    ]


def test_simulate_malformed_case_exits_2_naming_the_case(home):
    path = write_cases(home, [{"tool": "a", "expect": "allow"}, {"expect": "allow"}])

    result = policy(home, "simulate", path)

    assert result.exit_code == 2
    assert result.stderr.startswith("tony:") and "case 2" in result.stderr


def test_simulate_missing_file_exits_2(home):
    result = policy(home, "simulate", str(home / "absent.json"))

    assert result.exit_code == 2 and result.stderr.startswith("tony:")


def test_simulate_does_not_modify_the_policy(home):
    path = write_cases(home, [{"tool": "x", "expect": "confirm"}])
    before = policy_bytes(home)

    policy(home, "simulate", path)

    assert policy_bytes(home) == before


def test_policy_without_a_valid_policy_file_exits_2(tmp_path):
    result = policy(tmp_path / "empty", "grants")

    assert result.exit_code == 2 and result.stderr.startswith("tony:")
