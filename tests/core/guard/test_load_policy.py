import hashlib

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.guard.policy import load_policy, load_policy_with_version

FILE = "agents/edith/policy.yaml"


def write_policy(root, text, guard="edith"):
    folder = root / "agents" / guard
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "policy.yaml").write_text(text)


def load_error(root, guard="edith"):
    with pytest.raises(DefinitionError) as info:
        load_policy(root, guard)
    return info.value


def test_loads_policy_of_the_named_guard(tmp_path):
    write_policy(tmp_path, "default: deny\nrules:\n  - match: a.b\n    verdict: allow\n", "otra")

    policy = load_policy(tmp_path, "otra")

    assert policy.default == "deny"
    assert [rule.id for rule in policy.rules] == ["a.b/allow"]


def test_missing_file_names_it(tmp_path):
    error = load_error(tmp_path)

    assert (error.file, error.field, error.message) == (FILE, None, f"missing file {FILE}")


def test_invalid_yaml_names_file(tmp_path):
    write_policy(tmp_path, "default: [unclosed\n")

    error = load_error(tmp_path)

    assert (error.file, error.field) == (FILE, None)
    assert "invalid YAML" in error.message


@pytest.mark.parametrize("text", ["", "- a\n- b\n", "solo texto\n"])
def test_non_mapping_rejected(tmp_path, text):
    write_policy(tmp_path, text)

    error = load_error(tmp_path)

    assert (error.file, error.field, error.message) == (FILE, None, "must be a YAML mapping")


def test_schema_error_names_file_and_field(tmp_path):
    write_policy(tmp_path, "default: confirm\nlimits:\n  max_cost: 3\n")

    error = load_error(tmp_path)

    assert (error.file, error.field) == (FILE, "limits.max_cost")
    assert str(error).startswith(f"{FILE}: limits.max_cost: ")


POLICY_TEXT = "default: deny\nrules:\n  - match: a.b\n    verdict: allow\n"


def test_version_is_sha256_of_file_bytes_and_policy_matches_load_policy(tmp_path):
    write_policy(tmp_path, POLICY_TEXT)

    policy, version = load_policy_with_version(tmp_path, "edith")

    assert version == hashlib.sha256(POLICY_TEXT.encode()).hexdigest()
    assert policy == load_policy(tmp_path, "edith")


def test_comment_only_edit_changes_the_version(tmp_path):
    write_policy(tmp_path, POLICY_TEXT)
    _, before = load_policy_with_version(tmp_path, "edith")

    write_policy(tmp_path, POLICY_TEXT + "# nota\n")
    policy, after = load_policy_with_version(tmp_path, "edith")

    assert after != before
    assert policy == load_policy(tmp_path, "edith")


def test_version_of_an_invalid_file_raises_definition_error(tmp_path):
    write_policy(tmp_path, "- a\n")

    with pytest.raises(DefinitionError):
        load_policy_with_version(tmp_path, "edith")
