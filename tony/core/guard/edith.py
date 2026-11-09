import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import PolicySource
from tony.core.events.messages import Ruling, ToolCall, UserDecision
from tony.core.guard.allow_always import offers_allow_always
from tony.core.guard.audit import AuditLog, args_hash, args_preview
from tony.core.guard.confirm import ConfirmationRequest, Confirmer
from tony.core.guard.evaluate import Verdict, evaluate
from tony.core.guard.policy import Policy
from tony.core.guard.previews import build_preview
from tony.core.guard.wording import QuestionWording, worded_question
from tony.core.logging.task_log import Clock, utc_now

MAX_RE_EVALUATIONS = 2
"""Times a policy edit during a question may restart the judgement before the call is denied."""


@dataclass(frozen=True)
class _Judgement:
    verdict: Verdict
    user_decision: UserDecision | None = None
    approval_id: str | None = None


class EdithGuard:
    """Guard adapter: deterministic policy verdict, user confirmation and audit."""

    def __init__(
        self,
        policy: PolicySource,
        *,
        confirmer: Confirmer,
        wording: QuestionWording | None,
        audit: AuditLog,
        masker: SecretMasker,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Clock = utc_now,
    ) -> None:
        self._policy = policy
        self._confirmer = confirmer
        self._wording = wording
        self._audit = audit
        self._masker = masker
        self._monotonic = monotonic
        self._clock = clock

    async def decide(self, call: ToolCall) -> Ruling:
        start = self._monotonic()
        preview = args_preview(call.args, self._masker)
        judgement = await self._judge(call, preview)
        verdict = judgement.verdict
        ruling = Ruling(
            verdict=verdict.verdict, rule=verdict.rule, user_decision=judgement.user_decision
        )
        duration_ms = round((self._monotonic() - start) * 1000)
        self._audit.append(
            call,
            ruling,
            args_preview=preview,
            duration_ms=duration_ms,
            approval_id=judgement.approval_id,
        )
        return ruling

    async def _judge(self, call: ToolCall, preview: str) -> _Judgement:
        """Evaluate and, when needed, ask; a policy edit during the question voids the answer."""
        for _ in range(MAX_RE_EVALUATIONS + 1):
            policy = self._policy.current()
            version = self._policy.version()
            verdict = evaluate(policy, call.tool, call.args)
            if verdict.verdict != "confirm":
                return _Judgement(verdict)
            approval_id = str(uuid.uuid4())
            decision = await self._ask_user(
                policy, version, approval_id, call, preview, verdict.rule
            )
            if decision != "allow" or self._policy.version() == version:
                return _Judgement(verdict, decision, approval_id)
        return _Judgement(verdict, "deny", approval_id)

    async def _ask_user(
        self,
        policy: Policy,
        version: str,
        approval_id: str,
        call: ToolCall,
        preview: str,
        rule: str,
    ) -> UserDecision:
        question = await worded_question(self._wording, call.tool, preview, rule)
        timeout = policy.limits.confirm_timeout_s
        request = ConfirmationRequest(
            task_id=call.task_id,
            tool=call.tool,
            args_preview=preview,
            question=question,
            allow_always=offers_allow_always(policy, call.tool),
            approval_id=approval_id,
            args_digest=args_hash(call.args),
            policy_version=version,
            expires_at=self._expiry(timeout),
            preview=build_preview(call.tool, call.args, self._masker),
        )
        try:
            answer = await asyncio.wait_for(self._confirmer.ask(request), timeout)
        except TimeoutError:
            return "timeout"
        return "allow" if answer is True else "deny"

    def _expiry(self, timeout_s: float) -> datetime:
        return self._clock() + timedelta(seconds=timeout_s)
