from pydantic import BaseModel, ConfigDict, Field

from tony.core.events.messages import Decision


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rule(_Strict):
    match: str
    verdict: Decision


class Limits(_Strict):
    tool_timeout_s: float = 20
    task_timeout_s: float = 300
    confirm_timeout_s: float = 60
    max_denied_retries: int = 3
    token_alert: int = 50000
    max_steps_per_agent: int = 30


class Auth(_Strict):
    pin_required: bool = True
    lock_after_min: int = 30


class Policy(_Strict):
    default: Decision
    rules: list[Rule] = []
    limits: Limits = Field(default_factory=Limits)
    auth: Auth = Field(default_factory=Auth)
