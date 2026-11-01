from fnmatch import fnmatchcase
from typing import Any, NamedTuple

from tony.core.events.messages import Decision
from tony.core.guard.policy import Policy, Rule, When

DEFAULT_RULE = "default"


class Verdict(NamedTuple):
    verdict: Decision
    rule: str


def evaluate(policy: Policy, tool: str, args: dict[str, Any]) -> Verdict:
    for rule in policy.rules:
        if _matches(rule, tool) and _holds(rule.when, args):
            return Verdict(rule.verdict, rule.id)
    return Verdict(policy.default, DEFAULT_RULE)


def _matches(rule: Rule, tool: str) -> bool:
    return any(fnmatchcase(tool, pattern) for pattern in rule.match)


def _holds(when: When, args: dict[str, Any]) -> bool:
    if when.args_regex is not None:
        strings = [value for value in args.values() if isinstance(value, str)]
        if not any(when.args_regex.search(value) for value in strings):
            return False
    return True
