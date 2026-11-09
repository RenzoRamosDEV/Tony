from typing import Any


class FakeSnapshots:
    """In-memory ActionSnapshots recording the order of its calls against a recorder."""

    def __init__(self, recorder=None, *, fail: bool = False) -> None:
        self.recorder = recorder
        self.fail = fail
        self.kept: list[tuple[str, str, dict[str, Any]]] = []
        self.states_when_kept: list[list[str]] = []

    def keep(self, call_id: str, tool_id: str, args: dict[str, Any]) -> None:
        if tool_id != "filesystem.write_file":
            return
        if self.fail:
            raise OSError("undo dir not writable")
        self.kept.append((call_id, tool_id, args))
        if self.recorder is not None:
            self.states_when_kept.append(self.recorder.states(call_id))

    def written_digest(self, tool_id: str, args: dict[str, Any]) -> str:
        return f"sha256=fake-{args['content']}" if tool_id == "filesystem.write_file" else ""
