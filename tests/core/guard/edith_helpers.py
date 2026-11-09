import json
from datetime import UTC, datetime

from tests.fakes.confirm import FakeConfirmer
from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import StaticPolicy
from tony.core.events.messages import ToolCall
from tony.core.guard.audit import AUDIT_FILE, AuditLog
from tony.core.guard.edith import EdithGuard
from tony.core.guard.policy import Policy

POLICY = Policy.model_validate(
    {
        "default": "confirm",
        "rules": [
            {"match": "filesystem.read_*", "verdict": "allow"},
            {"match": "shell.run", "verdict": "deny"},
            {"match": "filesystem.delete*", "verdict": "confirm"},
        ],
        "limits": {"confirm_timeout_s": 0.2},
    }
)


class TickingClock:
    """Monotonic clock returning the scripted readings in order."""

    def __init__(self, *readings: float) -> None:
        self._readings = list(readings)

    def __call__(self) -> float:
        return self._readings.pop(0)


def call(tool, args=None):
    return ToolCall(task_id="t" * 32, agent="viernes", tool=tool, args=args or {})


NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


class MutablePolicySource:
    """PolicySource whose policy and version a test (or a confirmer) swaps at will."""

    def __init__(self, policy, version="v1"):
        self.policy = policy
        self.policy_version = version

    def current(self):
        return self.policy

    def version(self):
        return self.policy_version

    def swap(self, policy, version):
        self.policy, self.policy_version = policy, version


def make_edith(
    root,
    *,
    confirmer=None,
    wording=None,
    readings=(1.0, 1.0),
    policy=POLICY,
    source=None,
    clock=lambda: NOW,
):
    confirmer = confirmer or FakeConfirmer()
    edith = EdithGuard(
        source or StaticPolicy(policy, "v1"),
        confirmer=confirmer,
        wording=wording,
        audit=AuditLog(root, clock=lambda: datetime(2026, 11, 1, 9, 0, tzinfo=UTC)),
        masker=SecretMasker({"s3cr3t"}),
        monotonic=TickingClock(*readings),
        clock=clock,
    )
    return edith, confirmer


def audit_lines(root):
    path = root / AUDIT_FILE
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
