import json
from datetime import UTC, datetime

from tests.fakes.confirm import FakeConfirmer
from tony.core.config.placeholders import SecretMasker
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


def make_edith(root, *, confirmer=None, wording=None, readings=(1.0, 1.0), policy=POLICY):
    confirmer = confirmer or FakeConfirmer()
    edith = EdithGuard(
        policy,
        confirmer=confirmer,
        wording=wording,
        audit=AuditLog(root, clock=lambda: datetime(2026, 11, 1, 9, 0, tzinfo=UTC)),
        masker=SecretMasker({"s3cr3t"}),
        monotonic=TickingClock(*readings),
    )
    return edith, confirmer


def audit_lines(root):
    path = root / AUDIT_FILE
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
