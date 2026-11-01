import asyncio
from collections import Counter

from tony.core.events import log_events
from tony.core.events.messages import UserDecision
from tony.core.guard.policy import Limits
from tony.core.orchestrator.ports import EventSink

CANCELLED = "tarea cancelada"


class TaskSupervisor:
    """Per-task limits around a worker run; any breach cancels the whole task once."""

    def __init__(self, limits: Limits, sink: EventSink) -> None:
        self.cancelled = asyncio.Event()
        self.reason: str | None = None
        self.limits = limits
        self._sink = sink
        self._steps: Counter[str] = Counter()
        self._denials: Counter[str] = Counter()
        self._total_tokens = 0
        self._alerted = False

    def step(self, agent: str) -> bool:
        if self.cancelled.is_set():
            return False
        self._steps[agent] += 1
        limit = self.limits.max_steps_per_agent
        if self._steps[agent] > limit:
            self.cancel(f"{CANCELLED}: {agent} superó el límite de {limit} pasos")
            return False
        return True

    def denied(self, tool: str, rule: str) -> None:
        self._denials[tool] += 1
        count = self._denials[tool]
        if count >= self.limits.max_denied_retries:
            self.cancel(
                f"{CANCELLED}: {tool} bloqueada {count} veces por la política (regla {rule})"
            )

    def unconfirmed(self, tool: str, rule: str, user_decision: UserDecision | None) -> None:
        if user_decision == "timeout":
            wait = f"{self.limits.confirm_timeout_s:g}"
            self.cancel(
                f"{CANCELLED}: sin respuesta a la confirmación de {tool} en {wait} s (regla {rule})"
            )
        else:
            self.cancel(f"{CANCELLED}: el usuario no autorizó {tool} (regla {rule})")

    def cancel(self, reason: str) -> None:
        if not self.cancelled.is_set():
            self.reason = reason
            self.cancelled.set()

    def record_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        self._total_tokens += input_tokens + output_tokens
        limit = self.limits.token_alert
        if self._total_tokens > limit and not self._alerted:
            self._alerted = True
            self._sink.emit(log_events.token_alert(total_tokens=self._total_tokens, limit=limit))
