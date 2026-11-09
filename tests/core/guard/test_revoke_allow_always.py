import shutil
from pathlib import Path

import pytest
import yaml

from tony.core.guard.allow_always import insert_allow_always, revoke_allow_always
from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import load_policy

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(REPO / "agents" / "edith", tmp_path / "agents" / "edith")
    return tmp_path


def policy_path(root):
    return root / "agents" / "edith" / "policy.yaml"


def test_revoke_removes_only_that_grant_and_keeps_the_rest_in_order(root):
    original = yaml.safe_load(policy_path(root).read_text())
    insert_allow_always(root, "edith", "fs.write")
    insert_allow_always(root, "edith", "fs.read")
    with_grants = yaml.safe_load(policy_path(root).read_text())

    assert revoke_allow_always(root, "edith", "fs.write") is True

    after = yaml.safe_load(policy_path(root).read_text())
    assert after["rules"] == [
        rule for rule in with_grants["rules"] if rule.get("id") != "user-always/fs.write"
    ]
    assert after["rules"][0]["id"] == "user-always/fs.read"
    assert after["rules"][1:] == original["rules"]
    assert list(after) == list(with_grants)
    assert {k: after[k] for k in ("default", "limits", "auth")} == {
        k: original[k] for k in ("default", "limits", "auth")
    }


def test_revoked_tool_goes_back_to_the_policy_verdict(root):
    before = evaluate(load_policy(root, "edith"), "filesystem.delete_file", {"path": "/x"})
    insert_allow_always(root, "edith", "filesystem.delete_file")

    revoke_allow_always(root, "edith", "filesystem.delete_file")

    assert evaluate(load_policy(root, "edith"), "filesystem.delete_file", {"path": "/x"}) == before


def test_unknown_grant_returns_false_and_leaves_the_bytes_untouched(root):
    before = policy_path(root).read_bytes()

    assert revoke_allow_always(root, "edith", "fs.write") is False

    assert policy_path(root).read_bytes() == before


def test_shipped_rule_ids_are_not_removable(root):
    before = policy_path(root).read_bytes()

    assert revoke_allow_always(root, "edith", "shell.run") is False
    assert revoke_allow_always(root, "edith", "shell.run/deny") is False
    assert revoke_allow_always(root, "edith", "user-always/fs.write") is False

    assert policy_path(root).read_bytes() == before


def test_a_rewrite_that_would_not_validate_leaves_the_file_unchanged(root):
    insert_allow_always(root, "edith", "fs.write")
    data = yaml.safe_load(policy_path(root).read_text())
    data["rules"].append({"match": "x", "verdict": "maybe", "id": "bad"})
    policy_path(root).write_text(yaml.safe_dump(data, sort_keys=False))
    before = policy_path(root).read_bytes()

    with pytest.raises(ValueError):
        revoke_allow_always(root, "edith", "fs.write")

    assert policy_path(root).read_bytes() == before


def test_write_failure_leaves_the_file_unchanged(root):
    insert_allow_always(root, "edith", "fs.write")
    folder = policy_path(root).parent
    before = policy_path(root).read_bytes()
    folder.chmod(0o500)
    try:
        with pytest.raises(OSError):
            revoke_allow_always(root, "edith", "fs.write")
    finally:
        folder.chmod(0o700)

    assert policy_path(root).read_bytes() == before
    assert sorted(path.name for path in folder.iterdir()) == ["agent.md", "policy.yaml"]
