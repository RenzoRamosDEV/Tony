import pytest

from tests.core.guard.edith_helpers import call, make_edith
from tests.core.guard.shipped_policy import SHIPPED_POLICY_DATA
from tests.fakes.confirm import FakeConfirmer
from tony.core.guard.allow_always import offers_allow_always
from tony.core.guard.policy import Policy

SHIPPED = Policy.model_validate(SHIPPED_POLICY_DATA)


def policy(*rules):
    return Policy.model_validate({"default": "confirm", "rules": list(rules)})


@pytest.mark.parametrize(
    ("tool", "offered"),
    [
        ("shell.run", False),
        ("filesystem.delete_file", True),
        ("filesystem.write_file", True),
        ("filesystem.move_file", True),
        ("Shell.run", True),
        ("github.create_issue", True),
    ],
)
def test_shipped_policy(tool, offered):
    assert offers_allow_always(SHIPPED, tool) is offered


def test_deny_glob_blocks_every_matching_tool():
    assert offers_allow_always(policy({"match": "net.*", "verdict": "deny"}), "net.fetch") is False


def test_deny_pattern_second_in_a_list_blocks():
    rule = {"match": ["a.b", "net.fetch"], "verdict": "deny"}

    assert offers_allow_always(policy(rule), "net.fetch") is False


def test_non_deny_rules_do_not_block():
    rules = [{"match": "net.*", "verdict": "confirm"}, {"match": "net.*", "verdict": "allow"}]

    assert offers_allow_always(policy(*rules), "net.fetch") is True


def test_deny_rule_for_another_tool_does_not_block():
    assert offers_allow_always(policy({"match": "x.y", "verdict": "deny"}), "net.fetch") is True


def test_policy_without_rules_offers():
    assert offers_allow_always(policy(), "net.fetch") is True


@pytest.mark.parametrize(
    ("tool", "offered"), [("shell.run", False), ("filesystem.delete_file", True)]
)
async def test_edith_sets_allow_always_on_the_request(tmp_path, tool, offered):
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([False]), policy=SHIPPED)

    await edith.decide(call(tool, {"command": "ls"} if tool == "shell.run" else {"path": "a"}))

    [request] = confirmer.requests
    assert request.allow_always is offered
