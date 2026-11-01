import pytest

from tony.core.guard.evaluate import Verdict, evaluate
from tony.core.guard.policy import Policy


def policy(rules, default="confirm"):
    return Policy.model_validate({"default": default, "rules": rules})


ORDERED = policy(
    [
        {"match": "filesystem.read_*", "verdict": "allow"},
        {"match": ["filesystem.delete*", "filesystem.move_file"], "verdict": "confirm"},
        {"match": "shell.run", "verdict": "deny", "when": {"args_regex": "sudo"}},
        {"match": "shell.run", "verdict": "confirm"},
        {"match": "github.search_*", "verdict": "allow"},
        {"match": "github.*", "verdict": "confirm"},
        {"match": "github.*", "verdict": "allow", "id": "never-reached"},
    ]
)


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("filesystem.read_file", {}, Verdict("allow", "filesystem.read_*/allow")),
        ("filesystem.delete_file", {}, Verdict("confirm", "filesystem.delete*/confirm")),
        ("filesystem.move_file", {}, Verdict("confirm", "filesystem.delete*/confirm")),
        ("shell.run", {"command": "sudo dnf"}, Verdict("deny", "shell.run/deny")),
        ("shell.run", {"command": "ls"}, Verdict("confirm", "shell.run/confirm")),
        ("github.search_code", {}, Verdict("allow", "github.search_*/allow")),
        ("github.create_issue", {}, Verdict("confirm", "github.*/confirm")),
    ],
)
def test_first_matching_rule_wins(tool, args, expected):
    assert evaluate(ORDERED, tool, args) == expected


@pytest.mark.parametrize(
    "tool", ["Filesystem.read_file", "FILESYSTEM.READ_FILE", "filesystem.read", "foo.bar", ""]
)
def test_no_matching_rule_uses_default(tool):
    assert evaluate(ORDERED, tool, {}) == Verdict("confirm", "default")


@pytest.mark.parametrize("default", ["allow", "deny"])
def test_default_verdict_from_policy(default):
    assert evaluate(policy([], default), "foo.bar", {}) == Verdict(default, "default")


def test_rule_whose_condition_fails_falls_through_to_default():
    only = policy([{"match": "shell.run", "verdict": "deny", "when": {"args_regex": "sudo"}}])

    assert evaluate(only, "shell.run", {"command": "ls"}) == Verdict("confirm", "default")


def test_explicit_rule_id_reported():
    named = policy([{"id": "no-shell", "match": "shell.*", "verdict": "deny"}])

    assert evaluate(named, "shell.run", {}) == Verdict("deny", "no-shell")
