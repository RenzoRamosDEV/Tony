from tony.core.memory.actions import ActionState


class FakeRecorder:
    """In-memory ActionRecorder keeping every transition per call, in order."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.rows: dict[str, dict] = {}
        self.history: list[tuple[str, ActionState, str]] = []

    def prepared(self, task_id: str, agent: str, tool: str, args_digest: str) -> str:
        if self.fail:
            raise OSError("disk full")
        call_id = f"call-{len(self.rows) + 1}"
        self.rows[call_id] = {
            "task_id": task_id,
            "agent": agent,
            "tool": tool,
            "args_digest": args_digest,
        }
        self.history.append((call_id, "prepared", ""))
        return call_id

    def transition(self, call_id: str, state: ActionState, detail: str = "") -> None:
        if self.fail:
            raise OSError("disk full")
        self.history.append((call_id, state, detail))

    def states(self, call_id: str = "call-1") -> list[str]:
        return [state for id, state, _ in self.history if id == call_id]


def seed_stale_rows(home):
    """A previous run's journal: one call left `dispatched`, one `prepared`, one `succeeded`."""
    from datetime import UTC, datetime

    from tony.core.config.placeholders import SecretMasker
    from tony.core.memory.actions import ActionJournal

    journal = ActionJournal(home, SecretMasker(), clock=lambda: datetime(2020, 1, 1, tzinfo=UTC))
    ids = {}
    for name in ("dispatched", "prepared", "succeeded"):
        ids[name] = journal.prepared("old", "viernes", "gmail.send_email", "d")
        if name != "prepared":
            journal.transition(ids[name], name)
    journal.close()
    return ids


def states_on_disk(home):
    from tony.core.config.placeholders import SecretMasker
    from tony.core.memory.actions import ActionJournal

    journal = ActionJournal(home, SecretMasker())
    try:
        return {record.call_id: record.state for record in journal.list(limit=100)}
    finally:
        journal.close()
