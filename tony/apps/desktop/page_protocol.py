"""Qt-free half of the page channel: validating page commands and remembering the events a
freshly loaded page needs to catch up."""

import json
from dataclasses import dataclass
from typing import Any

from tony.core.events import core_events
from tony.core.events.core_events import Event
from tony.core.orchestrator.commands import InvalidCommand, Stop, parse_command

_LATEST_ONLY = ("voice_state", "reply_mode", "auth")


@dataclass(frozen=True)
class Accepted:
    command: dict[str, Any]


@dataclass(frozen=True)
class Rejected:
    event: Event


class PageCommandGate:
    """Decodes and validates page commands with the core's rules; the internal `stop` is
    refused. Errors name the command type and field, never the submitted values."""

    def accept(self, text: str) -> Accepted | Rejected:
        try:
            raw = json.loads(text)
        except ValueError:
            return Rejected(core_events.error("page", "malformed command JSON"))
        if not isinstance(raw, dict):
            return Rejected(core_events.error("page", "a command must be a JSON object"))
        try:
            command = parse_command(raw)
        except InvalidCommand as error:
            return Rejected(core_events.error(error.command_type, str(error)))
        if isinstance(command, Stop):
            return Rejected(
                core_events.error("stop", "command 'stop' is not allowed from the page")
            )
        return Accepted(raw)


class EventReplay:
    """Latest state-carrying events: voice state, reply mode, auth, MCP status per agent and
    server, and the pending confirmation until its task is answered or ends."""

    def __init__(self) -> None:
        self._latest: dict[str, Event] = {}
        self._servers: dict[tuple[str, str], Event] = {}
        self._confirmation: Event | None = None

    def observe(self, event: Event) -> None:
        kind = event["type"]
        if kind in _LATEST_ONLY:
            self._latest[kind] = event
        elif kind == "mcp_status":
            self._servers[(event["agent"], event["server"])] = event
        elif kind == "needs_confirmation":
            self._confirmation = event
        elif self._answers_confirmation(event):
            self._confirmation = None

    def snapshot(self) -> list[Event]:
        latest = [self._latest[kind] for kind in _LATEST_ONLY if kind in self._latest]
        pending = [] if self._confirmation is None else [self._confirmation]
        return [*latest, *self._servers.values(), *pending]

    def _answers_confirmation(self, event: Event) -> bool:
        if self._confirmation is None or event.get("task_id") != self._confirmation["task_id"]:
            return False
        return event["type"] == "tool_call" or (
            event["type"] == "result" and event["scope"] == "task"
        )
