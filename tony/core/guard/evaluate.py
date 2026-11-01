import os
from collections.abc import Iterator
from fnmatch import fnmatchcase
from pathlib import Path
from re import Pattern
from typing import Any, NamedTuple

from tony.core.events.messages import Decision
from tony.core.guard.policy import NumericAbove, Policy, Rule, When

DEFAULT_RULE = "default"
PATH_KEYS = ("path", "source", "destination")
PATHS_KEY = "paths"


class Verdict(NamedTuple):
    verdict: Decision
    rule: str


def evaluate(policy: Policy, tool: str, args: dict[str, Any]) -> Verdict:
    for rule in policy.rules:
        if rule_matches(rule, tool) and _holds(rule.when, args):
            return Verdict(rule.verdict, rule.id)
    return Verdict(policy.default, DEFAULT_RULE)


def rule_matches(rule: Rule, tool: str) -> bool:
    return any(fnmatchcase(tool, pattern) for pattern in rule.match)


def _holds(when: When, args: dict[str, Any]) -> bool:
    if when.path_outside is not None and not _path_outside(when.path_outside, args):
        return False
    if when.args_regex is not None and not _args_match(when.args_regex, args):
        return False
    if when.numeric_above is not None and not _numeric_above(when.numeric_above, args):
        return False
    return True


def _args_match(pattern: Pattern[str], args: dict[str, Any]) -> bool:
    return any(pattern.search(value) for value in _strings(args))


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def _numeric_above(condition: NumericAbove, args: dict[str, Any]) -> bool:
    value = args.get(condition.arg)
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    return is_number and value > condition.value


def _path_outside(folders: list[str], args: dict[str, Any]) -> bool:
    allowed = [_normalise(folder) for folder in folders]
    return any(
        not any(path.is_relative_to(folder) for folder in allowed)
        for path in map(_normalise, _path_args(args))
    )


def _path_args(args: dict[str, Any]) -> Iterator[str]:
    for key in PATH_KEYS:
        if isinstance(args.get(key), str):
            yield args[key]
    paths = args.get(PATHS_KEY)
    if isinstance(paths, list):
        yield from (item for item in paths if isinstance(item, str))


def _normalise(path: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(path)))
