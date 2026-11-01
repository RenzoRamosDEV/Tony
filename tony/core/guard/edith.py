import asyncio
import time
from collections.abc import Callable

from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import PolicySource
from tony.core.events.messages import Ruling, ToolCall, UserDecision
from tony.core.guard.allow_always import offers_allow_always
from tony.core.guard.audit import AuditLog, args_preview
from tony.core.guard.confirm import ConfirmationRequest, Confirmer
from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import Policy
from tony.core.guard.wording import QuestionWording, worded_question


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
    ) -> None:
        self._policy = policy
        self._confirmer = confirmer
        self._wording = wording
        self._audit = audit
        self._masker = masker
        self._monotonic = monotonic

    async def decide(self, call: ToolCall) -> Ruling:
        start = self._monotonic()
        policy = self._policy.current()
        verdict = evaluate(policy, call.tool, call.args)
        preview = args_preview(call.args, self._masker)
        user_decision = None
        if verdict.verdict == "confirm":
            user_decision = await self._ask_user(policy, call, preview, verdict.rule)
        ruling = Ruling(verdict=verdict.verdict, rule=verdict.rule, user_decision=user_decision)
        duration_ms = round((self._monotonic() - start) * 1000)
        self._audit.append(call, ruling, args_preview=preview, duration_ms=duration_ms)
        return ruling

    async def _ask_user(
        self, policy: Policy, call: ToolCall, preview: str, rule: str
    ) -> UserDecision:
        question = await worded_question(self._wording, call.tool, preview, rule)
        request = ConfirmationRequest(
            task_id=call.task_id,
            tool=call.tool,
            args_preview=preview,
            question=question,
            allow_always=offers_allow_always(policy, call.tool),
        )
        timeout = policy.limits.confirm_timeout_s
        try:
            answer = await asyncio.wait_for(self._confirmer.ask(request), timeout)
        except TimeoutError:
            return "timeout"
        return "allow" if answer is True else "deny"
