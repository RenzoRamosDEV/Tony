import pytest
from pydantic import ValidationError

from tony.core.config.errors import DefinitionError
from tony.core.guard.policy import Auth, Limits, Policy

FILE = "agents/edith/policy.yaml"


def field_of(data):
    with pytest.raises(ValidationError) as info:
        Policy.model_validate(data)
    return DefinitionError.from_validation(FILE, info.value).field


def test_only_default_takes_every_other_default():
    policy = Policy.model_validate({"default": "confirm"})

    assert policy.default == "confirm"
    assert policy.rules == []
    assert policy.limits == Limits(
        tool_timeout_s=20,
        task_timeout_s=300,
        confirm_timeout_s=60,
        max_denied_retries=3,
        token_alert=50000,
        max_steps_per_agent=30,
    )
    assert policy.auth == Auth(pin_required=True, lock_after_min=30)


@pytest.mark.parametrize("default", ["allow", "confirm", "deny"])
def test_every_verdict_is_a_valid_default(default):
    assert Policy.model_validate({"default": default}).default == default


@pytest.mark.parametrize("default", ["maybe", "Allow", "", None])
def test_invalid_default_rejected(default):
    assert field_of({"default": default}) == "default"


def test_default_required():
    assert field_of({"rules": []}) == "default"


def test_limits_values_can_be_overridden():
    policy = Policy.model_validate({"default": "deny", "limits": {"task_timeout_s": 1}})

    assert policy.limits.task_timeout_s == 1
    assert policy.limits.tool_timeout_s == 20


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"default": "deny", "extra": 1}, "extra"),
        ({"default": "deny", "limits": {"max_cost": 3}}, "limits.max_cost"),
        ({"default": "deny", "auth": {"pin": "1234"}}, "auth.pin"),
        (
            {"default": "deny", "rules": [{"match": "a", "verdict": "allow", "foo": 1}]},
            "rules.0.foo",
        ),
        (
            {
                "default": "deny",
                "rules": [
                    {"match": "a", "verdict": "allow"},
                    {"match": "b", "verdict": "maybe"},
                ],
            },
            "rules.1.verdict",
        ),
    ],
)
def test_unknown_keys_and_invalid_values_name_dotted_field(data, field):
    assert field_of(data) == field
