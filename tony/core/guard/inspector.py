import json
from dataclasses import dataclass
from typing import Any, get_args

from tony.core.events.messages import Decision
from tony.core.guard.allow_always import ALLOW_ALWAYS_PREFIX
from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import Policy

CASE_KEYS = {"tool", "args", "expect"}


class MalformedCases(Exception):
    pass


@dataclass(frozen=True)
class Explanation:
    verdict: Decision
    rule: str
    position: int | None


@dataclass(frozen=True)
class Case:
    tool: str
    args: dict[str, Any]
    expect: Decision


@dataclass(frozen=True)
class CaseResult:
    index: int
    tool: str
    expected: Decision
    actual: Decision

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


def explain(policy: Policy, tool: str, args: dict[str, Any]) -> Explanation:
    """The real verdict of `evaluate` plus the 1-based position of the rule that produced it."""
    verdict = evaluate(policy, tool, args)
    position = next(
        (index for index, rule in enumerate(policy.rules, 1) if rule.id == verdict.rule), None
    )
    return Explanation(verdict.verdict, verdict.rule, position)


def grants(policy: Policy) -> list[str]:
    return [
        rule.id.removeprefix(ALLOW_ALWAYS_PREFIX)
        for rule in policy.rules
        if rule.id is not None and rule.id.startswith(ALLOW_ALWAYS_PREFIX)
    ]


def simulate(policy: Policy, cases: list[Case]) -> list[CaseResult]:
    return [
        CaseResult(index, case.tool, case.expect, evaluate(policy, case.tool, case.args).verdict)
        for index, case in enumerate(cases, 1)
    ]


def parse_cases(text: str) -> list[Case]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise MalformedCases(f"file is not valid JSON: {error}") from error
    if not isinstance(raw, list):
        raise MalformedCases("file must be a JSON list of cases")
    return [_parse_case(index, item) for index, item in enumerate(raw, 1)]


def _parse_case(index: int, item: Any) -> Case:
    problem = _case_problem(item)
    if problem:
        raise MalformedCases(f"case {index}: {problem}")
    return Case(item["tool"], item.get("args", {}), item["expect"])


def _case_problem(item: Any) -> str | None:
    if not isinstance(item, dict):
        return "must be an object {tool, args, expect}"
    if unknown := sorted(set(item) - CASE_KEYS):
        return f"unknown keys {unknown}"
    if not isinstance(item.get("tool"), str):
        return "'tool' must be a string"
    if not isinstance(item.get("args", {}), dict):
        return "'args' must be an object"
    if item.get("expect") not in get_args(Decision):
        return f"'expect' must be one of {list(get_args(Decision))}"
    return None
