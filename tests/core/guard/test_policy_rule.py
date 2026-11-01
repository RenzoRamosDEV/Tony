import pytest
from pydantic import ValidationError

from tony.core.config.errors import DefinitionError
from tony.core.guard.policy import NumericAbove, Policy, Rule


def rule(**data):
    return Rule.model_validate(data)


def field_of(rules):
    with pytest.raises(ValidationError) as info:
        Policy.model_validate({"default": "deny", "rules": rules})
    return DefinitionError.from_validation("p.yaml", info.value).field


def test_single_pattern_becomes_a_list():
    assert rule(match="filesystem.read_*", verdict="allow").match == ["filesystem.read_*"]


def test_list_of_patterns_kept_in_order():
    r = rule(match=["filesystem.delete*", "filesystem.move_file"], verdict="confirm")

    assert r.match == ["filesystem.delete*", "filesystem.move_file"]


def test_derived_id_uses_first_pattern_and_verdict():
    r = rule(match=["filesystem.delete*", "filesystem.move_file"], verdict="confirm")

    assert r.id == "filesystem.delete*/confirm"


def test_explicit_id_kept():
    assert rule(id="no-shell", match="shell.run", verdict="deny").id == "no-shell"


def test_when_defaults_to_no_conditions():
    when = rule(match="a", verdict="allow").when

    assert (when.path_outside, when.args_regex, when.numeric_above) == (None, None, None)


def test_when_conditions_parsed():
    r = rule(
        match="a",
        verdict="deny",
        when={
            "path_outside": ["~/notas", "~/proyectos"],
            "args_regex": "(rm -rf|sudo)",
            "numeric_above": {"arg": "importe", "value": 100},
        },
    )

    assert r.when.path_outside == ["~/notas", "~/proyectos"]
    assert r.when.args_regex.search("sudo dnf")
    assert r.when.numeric_above == NumericAbove(arg="importe", value=100)


@pytest.mark.parametrize(
    ("bad_rule", "field"),
    [
        ({"match": [], "verdict": "allow"}, "rules.0.match"),
        ({"match": "", "verdict": "allow"}, "rules.0.match.0"),
        ({"verdict": "allow"}, "rules.0.match"),
        ({"match": "a"}, "rules.0.verdict"),
        (
            {"match": "a", "verdict": "deny", "when": {"args_regex": "(unclosed"}},
            "rules.0.when.args_regex",
        ),
        (
            {"match": "a", "verdict": "deny", "when": {"path_outside": "~/notas"}},
            "rules.0.when.path_outside",
        ),
        (
            {"match": "a", "verdict": "deny", "when": {"numeric_above": {"arg": "x"}}},
            "rules.0.when.numeric_above.value",
        ),
        (
            {
                "match": "a",
                "verdict": "deny",
                "when": {"numeric_above": {"arg": "x", "value": "1"}},
            },
            "rules.0.when.numeric_above.value",
        ),
        ({"match": "a", "verdict": "deny", "when": {"other": 1}}, "rules.0.when.other"),
    ],
)
def test_invalid_rule_names_dotted_field(bad_rule, field):
    assert field_of([bad_rule]) == field


def test_error_index_points_at_the_offending_rule():
    rules = [{"match": "a", "verdict": "allow"}, {"match": [], "verdict": "allow"}]

    assert field_of(rules) == "rules.1.match"


@pytest.mark.parametrize("value", [True, "1", None])
def test_numeric_above_value_must_be_a_number(value):
    bad = {"match": "a", "verdict": "deny", "when": {"numeric_above": {"arg": "x", "value": value}}}

    assert field_of([bad]) == "rules.0.when.numeric_above.value"


def test_numeric_above_accepts_float():
    assert NumericAbove(arg="x", value=100.5).value == 100.5
