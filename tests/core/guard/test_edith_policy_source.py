import asyncio
from datetime import UTC, datetime

from tests.core.guard.edith_helpers import POLICY, TickingClock, call
from tests.fakes.confirm import HANG, FakeConfirmer
from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import StaticPolicy
from tony.core.guard.audit import AuditLog
from tony.core.guard.edith import EdithGuard
from tony.core.guard.policy import Policy

DENY_READS = Policy.model_validate(
    {
        "default": "confirm",
        "rules": [{"match": "filesystem.read_*", "verdict": "deny", "id": "no-read"}],
        "limits": {"confirm_timeout_s": 0.05},
    }
)


class MutablePolicy:
    def __init__(self, policy):
        self.policy = policy
        self.reads = 0

    def current(self):
        self.reads += 1
        return self.policy


def edith_for(root, source, confirmer=None):
    return EdithGuard(
        source,
        confirmer=confirmer or FakeConfirmer(),
        wording=None,
        audit=AuditLog(root, clock=lambda: datetime(2026, 11, 1, 9, 0, tzinfo=UTC)),
        masker=SecretMasker(),
        monotonic=TickingClock(*([1.0] * 10)),
    )


async def test_replacing_policy_changes_next_verdict(tmp_path):
    source = MutablePolicy(POLICY)
    edith = edith_for(tmp_path, source)

    first = await edith.decide(call("filesystem.read_file"))
    source.policy = DENY_READS
    second = await edith.decide(call("filesystem.read_file"))

    assert (first.verdict, first.rule) == ("allow", "filesystem.read_*/allow")
    assert (second.verdict, second.rule) == ("deny", "no-read")


async def test_policy_read_once_per_decision(tmp_path):
    source = MutablePolicy(POLICY)
    edith = edith_for(tmp_path, source, FakeConfirmer([True]))

    await edith.decide(call("filesystem.delete_file"))

    assert source.reads == 1


async def test_confirm_timeout_and_allow_always_from_current_policy(tmp_path):
    start = Policy.model_validate(
        {
            "default": "confirm",
            "rules": [{"match": "shell.run", "verdict": "deny", "when": {"args_regex": "rm"}}],
            "limits": {"confirm_timeout_s": 60},
        }
    )
    source = MutablePolicy(start)
    confirmer = FakeConfirmer([HANG])
    edith = edith_for(tmp_path, source, confirmer)
    source.policy = DENY_READS

    async with asyncio.timeout(5):
        ruling = await edith.decide(call("shell.run"))

    assert (ruling.verdict, ruling.user_decision) == ("confirm", "timeout")
    assert confirmer.requests[0].allow_always is True


async def test_static_policy_keeps_behaviour(tmp_path):
    edith = edith_for(tmp_path, StaticPolicy(POLICY))

    ruling = await edith.decide(call("shell.run"))

    assert (ruling.verdict, ruling.rule) == ("deny", "shell.run/deny")
    assert StaticPolicy(POLICY).current() is POLICY
