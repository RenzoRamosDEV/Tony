import time
from collections.abc import Callable

from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling, ToolCall
from tony.core.guard.audit import AuditLog, args_preview
from tony.core.guard.confirm import Confirmer
from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import Policy
from tony.core.guard.wording import QuestionWording


class EdithGuard:
    """Guard adapter: deterministic policy verdict, user confirmation and audit."""

    def __init__(
        self,
        policy: Policy,
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
        verdict = evaluate(self._policy, call.tool, call.args)
        preview = args_preview(call.args, self._masker)
        ruling = Ruling(verdict=verdict.verdict, rule=verdict.rule)
        duration_ms = round((self._monotonic() - start) * 1000)
        self._audit.append(call, ruling, args_preview=preview, duration_ms=duration_ms)
        return ruling
