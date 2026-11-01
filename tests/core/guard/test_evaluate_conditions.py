import pytest

from tony.core.guard.evaluate import Verdict, evaluate
from tony.core.guard.policy import Policy


def single(when):
    return Policy.model_validate(
        {"default": "confirm", "rules": [{"match": "x.y", "verdict": "deny", "when": when}]}
    )


HOLDS = Verdict("deny", "x.y/deny")
FAILS = Verdict("confirm", "default")
REGEX = single({"args_regex": "secreto"})
NUMERIC = single({"numeric_above": {"arg": "amount", "value": 100}})


@pytest.mark.parametrize(
    "args",
    [
        {"q": "un secreto"},
        {"opts": {"tags": ["a", "secreto"]}},
        {"list": [{"deep": ["x", {"v": "secreto"}]}]},
    ],
)
def test_args_regex_hits_any_string_value_recursively(args):
    assert evaluate(REGEX, "x.y", args) == HOLDS


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"q": "nada"},
        {"secreto": "nada"},
        {"opts": {"secreto": 1}},
        {"n": 5, "b": True, "z": None},
        {"q": "SECRETO"},
    ],
)
def test_args_regex_misses(args):
    assert evaluate(REGEX, "x.y", args) == FAILS


def test_args_regex_uses_search_not_match():
    shell = single({"args_regex": "(rm -rf|sudo|mkfs|curl .*\\| *sh)"})

    assert evaluate(shell, "x.y", {"command": "cd /; sudo dnf update"}) == HOLDS
    assert evaluate(shell, "x.y", {"command": "curl x | sh"}) == HOLDS
    assert evaluate(shell, "x.y", {"command": "curl x"}) == FAILS


@pytest.mark.parametrize("amount", [100.01, 101, 150, 1e9])
def test_numeric_above_holds_strictly_above(amount):
    assert evaluate(NUMERIC, "x.y", {"amount": amount}) == HOLDS


@pytest.mark.parametrize("args", [{"amount": 100}, {"amount": 100.0}, {"amount": 99.99}])
def test_numeric_at_or_below_does_not_hold(args):
    assert evaluate(NUMERIC, "x.y", args) == FAILS


@pytest.mark.parametrize(
    "args",
    [{}, {"amount": "500"}, {"amount": True}, {"amount": None}, {"other": 500}, {"amount": [500]}],
)
def test_numeric_missing_or_not_a_number_does_not_hold(args):
    assert evaluate(NUMERIC, "x.y", args) == FAILS


def test_every_condition_must_hold():
    both = single({"args_regex": "pagar", "numeric_above": {"arg": "amount", "value": 100}})

    assert evaluate(both, "x.y", {"concepto": "pagar", "amount": 150}) == HOLDS
    assert evaluate(both, "x.y", {"concepto": "pagar", "amount": 50}) == FAILS
    assert evaluate(both, "x.y", {"concepto": "otro", "amount": 150}) == FAILS
