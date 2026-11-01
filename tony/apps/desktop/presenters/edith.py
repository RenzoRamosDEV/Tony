from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tony.apps.desktop.presenters.chat import Submit
from tony.apps.desktop.presenters.observable import Observable
from tony.core.events.core_events import Event
from tony.core.guard.audit import AuditLine, read_audit, select_lines


@dataclass(frozen=True)
class PendingConfirmation:
    task_id: str
    tool: str
    args_preview: str
    question: str
    offers_always: bool


@dataclass(frozen=True)
class AuditRow:
    time: str
    agent: str
    tool: str
    verdict: str
    rule: str
    user_decision: str | None


class EdithPresenter(Observable):
    """Edith zone state: the pending confirmation banner and today's audit, filterable."""

    def __init__(self, submit: Submit, root: Path, *, now: Callable[[], datetime]) -> None:
        super().__init__()
        self._submit = submit
        self._root = root
        self._now = now
        self._rows: list[AuditRow] = []
        self.pending: PendingConfirmation | None = None
        self.verdict_filter: str | None = None

    @property
    def rows(self) -> list[AuditRow]:
        return [row for row in self._rows if self.verdict_filter in (None, row.verdict)]

    def load_audit(self) -> None:
        """Read-only file access to logs/audit.jsonl for the local date; not a core call."""
        lines, _ = read_audit(self._root)
        today = select_lines(lines, local_day_of=self._now())
        self._rows = [self._row(line) for line in today]
        self._changed()

    def set_filter(self, verdict: str | None) -> None:
        self.verdict_filter = verdict
        self._changed()

    def allow(self) -> None:
        self._answer("allow")

    def deny(self) -> None:
        self._answer("deny")

    def allow_always(self) -> None:
        if self.pending is not None and self.pending.offers_always:
            self._answer("always")

    def apply(self, event: Event) -> None:
        kind = event["type"]
        if kind == "needs_confirmation":
            self.pending = PendingConfirmation(
                event["task_id"],
                event["tool"],
                event["args_preview"],
                event["question"],
                event["allow_always"],
            )
        elif kind == "result" and event["scope"] == "task" and self._is_pending(event):
            self.pending = None
        elif kind == "tool_call":
            self._rows.append(self._row(event))
        else:
            return
        self._changed()

    def _is_pending(self, event: Event) -> bool:
        return self.pending is not None and self.pending.task_id == event["task_id"]

    def _answer(self, decision: str) -> None:
        if self.pending is None:
            return
        self._submit({"type": "confirm", "task_id": self.pending.task_id, "decision": decision})
        self.pending = None
        self._changed()

    def _row(self, line: AuditLine) -> AuditRow:
        local = datetime.fromisoformat(line["ts"]).astimezone(self._now().tzinfo)
        return AuditRow(
            time=local.strftime("%H:%M:%S"),
            agent=line["agent"],
            tool=line["tool"],
            verdict=line["verdict"],
            rule=line["rule"],
            user_decision=line["user_decision"],
        )
