import json
import typing

import pytest

from tony.core.guard.inspector import (
    MalformedCases,
    explain,
    grants,
    parse_cases,
    simulate,
)
from tony.core.guard.policy import Policy
from tony.core.orchestrator import commands
from tony.core.orchestrator.natives import NATIVE_TOOLS

POLICY = Policy.model_validate(
    {
        "default": "confirm",
        "rules": [
            {"match": "fs.write", "verdict": "allow", "id": "user-always/fs.write"},
            {"match": "shell.run", "verdict": "deny", "when": {"args_regex": "sudo"}},
            {"match": "shell.run", "verdict": "confirm"},
            {"match": "fs.read_*", "verdict": "allow", "id": "user-always/fs.read_*"},
            {"match": "net.get", "verdict": "allow"},
        ],
    }
)


def test_explain_reports_verdict_rule_and_one_based_position():
    result = explain(POLICY, "shell.run", {"cmd": "sudo ls"})

    assert (result.verdict, result.rule, result.position) == ("deny", "shell.run/deny", 2)


def test_explain_position_follows_first_match_not_the_last():
    result = explain(POLICY, "shell.run", {"cmd": "ls"})

    assert (result.verdict, result.rule, result.position) == ("confirm", "shell.run/confirm", 3)


def test_explain_first_rule_is_position_1():
    assert explain(POLICY, "fs.write", {}).position == 1


def test_explain_default_has_no_position():
    result = explain(POLICY, "unknown.tool", {})

    assert (result.verdict, result.rule, result.position) == ("confirm", "default", None)


def test_grants_lists_tool_ids_in_policy_order():
    assert grants(POLICY) == ["fs.write", "fs.read_*"]


def test_grants_ignores_rules_without_the_prefix():
    other = Policy.model_validate(
        {
            "default": "deny",
            "rules": [{"match": "a", "verdict": "allow", "id": "shipped/user-always/a"}],
        }
    )

    assert grants(other) == []


def test_no_grants():
    assert grants(Policy.model_validate({"default": "deny"})) == []


def cases(*items):
    return json.dumps(list(items))


def test_simulate_all_pass():
    parsed = parse_cases(
        cases(
            {"tool": "fs.write", "args": {}, "expect": "allow"},
            {"tool": "x.y", "expect": "confirm"},
        )
    )

    results = simulate(POLICY, parsed)

    assert [(r.index, r.passed, r.actual) for r in results] == [
        (1, True, "allow"),
        (2, True, "confirm"),
    ]


def test_simulate_reports_the_actual_verdict_of_a_failing_case():
    [result] = simulate(POLICY, parse_cases(cases({"tool": "x.y", "args": {}, "expect": "allow"})))

    assert (result.passed, result.expected, result.actual) == (False, "allow", "confirm")


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("not json", "file"),
        ('{"tool": "a"}', "file"),
        (cases({"tool": "a", "expect": "allow"}, {"args": {}, "expect": "allow"}), "case 2"),
        (cases({"tool": "a"}), "case 1"),
        (cases({"tool": "a", "expect": "maybe"}), "case 1"),
        (cases({"tool": 3, "expect": "allow"}), "case 1"),
        (cases({"tool": "a", "args": [1], "expect": "allow"}), "case 1"),
        (cases("text"), "case 1"),
        (cases({"tool": "a", "expect": "allow", "extra": 1}), "case 1"),
    ],
)
def test_malformed_input_names_the_problem(text, named):
    with pytest.raises(MalformedCases) as raised:
        parse_cases(text)

    assert named in str(raised.value)


def test_empty_case_list_is_valid():
    assert parse_cases("[]") == []


def test_policy_commands_are_neither_native_tools_nor_core_commands():
    command_types = {
        typing.get_args(member.model_fields["type"].annotation)[0]
        for member in typing.get_args(typing.get_args(commands.Command)[0])
    }
    exposed = {*command_types, *NATIVE_TOOLS}

    assert not [
        name
        for name in exposed
        if any(w in name for w in ("policy", "revoke", "simulate", "explain", "grants"))
    ]
