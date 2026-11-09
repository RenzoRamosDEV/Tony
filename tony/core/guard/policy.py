import hashlib
from pathlib import Path
from re import Pattern
from typing import Annotated, Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from tony.core.config.errors import DefinitionError
from tony.core.events.messages import Decision


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumericAbove(_Strict):
    arg: str
    value: float = Field(strict=True)


class When(_Strict):
    path_outside: list[str] | None = None
    args_regex: Pattern[str] | None = None
    numeric_above: NumericAbove | None = None


class Rule(_Strict):
    match: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    verdict: Decision
    id: str | None = None
    when: When = Field(default_factory=When)

    @field_validator("match", mode="before")
    @classmethod
    def _single_pattern_as_list(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    @model_validator(mode="after")
    def _derive_id(self) -> "Rule":
        if self.id is None:
            self.id = f"{self.match[0]}/{self.verdict}"
        return self


class Limits(_Strict):
    tool_timeout_s: float = 20
    task_timeout_s: float = 300
    confirm_timeout_s: float = 60
    max_denied_retries: int = 3
    token_alert: int = 50000
    max_steps_per_agent: int = 30
    tool_result_max_chars: int = 20000


class Auth(_Strict):
    pin_required: bool = True
    lock_after_min: int = 30


class Policy(_Strict):
    default: Decision
    rules: list[Rule] = []
    limits: Limits = Field(default_factory=Limits)
    auth: Auth = Field(default_factory=Auth)


def policy_file(guard: str) -> str:
    return f"agents/{guard}/policy.yaml"


def load_policy(root: Path, guard: str) -> Policy:
    return load_policy_with_version(root, guard)[0]


def load_policy_with_version(root: Path, guard: str) -> tuple[Policy, str]:
    """The guard's policy and the sha256 of the exact `policy.yaml` bytes it was parsed from."""
    file = policy_file(guard)
    path = root / file
    if not path.is_file():
        raise DefinitionError(file, None, f"missing file {file}")
    content = path.read_bytes()
    try:
        data = yaml.safe_load(content.decode())
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        raise DefinitionError(file, None, f"invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise DefinitionError(file, None, "must be a YAML mapping")
    try:
        policy = Policy.model_validate(data)
    except ValidationError as error:
        raise DefinitionError.from_validation(file, error) from error
    return policy, hashlib.sha256(content).hexdigest()
