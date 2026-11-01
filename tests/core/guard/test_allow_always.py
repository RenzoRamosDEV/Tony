import shutil
from pathlib import Path

import pytest
import yaml

from tony.core.guard.allow_always import insert_allow_always
from tony.core.guard.evaluate import Verdict, evaluate
from tony.core.guard.policy import load_policy

REPO = Path(__file__).resolve().parents[3]
TOOL = "filesystem.write_file"


@pytest.fixture
def root(tmp_path):
    shutil.copytree(REPO / "agents" / "edith", tmp_path / "agents" / "edith")
    return tmp_path


def policy_path(root):
    return root / "agents" / "edith" / "policy.yaml"


def test_inserts_the_rule_first_and_preserves_the_rest(root):
    before = yaml.safe_load(policy_path(root).read_text())

    insert_allow_always(root, "edith", TOOL)

    after = yaml.safe_load(policy_path(root).read_text())
    assert after["rules"][0] == {
        "match": TOOL,
        "verdict": "allow",
        "id": f"user-always/{TOOL}",
    }
    assert after["rules"][1:] == before["rules"]
    assert list(after) == list(before)
    assert {key: after[key] for key in ("default", "limits", "auth")} == {
        key: before[key] for key in ("default", "limits", "auth")
    }


def test_reloaded_policy_allows_the_tool_by_the_new_rule(root):
    insert_allow_always(root, "edith", TOOL)

    policy = load_policy(root, "edith")
    assert evaluate(policy, TOOL, {"path": "/tmp/a.md"}) == Verdict("allow", f"user-always/{TOOL}")


def test_existing_rule_leaves_the_file_byte_identical(root):
    insert_allow_always(root, "edith", TOOL)
    once = policy_path(root).read_bytes()

    insert_allow_always(root, "edith", TOOL)

    assert policy_path(root).read_bytes() == once


def test_keeps_unicode_readable(root):
    insert_allow_always(root, "edith", "github.crear_incidencia_año")

    assert "año" in policy_path(root).read_text(encoding="utf-8")


def test_unwritable_folder_raises_and_leaves_the_file_unchanged(root):
    folder = policy_path(root).parent
    before = policy_path(root).read_bytes()
    folder.chmod(0o500)
    try:
        with pytest.raises(OSError):
            insert_allow_always(root, "edith", TOOL)
    finally:
        folder.chmod(0o700)

    assert policy_path(root).read_bytes() == before
    assert sorted(path.name for path in folder.iterdir()) == ["agent.md", "policy.yaml"]
