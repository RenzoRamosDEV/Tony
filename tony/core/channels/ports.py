"""Channel port: typed messages the chat session sends to whatever faces the user."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class UserAccepted:
    message_id: str
    effective_mode: str


@dataclass(frozen=True)
class AssistantDelta:
    message_id: str
    text: str


@dataclass(frozen=True)
class AssistantSpeechDelta:
    """A fragment of the spoken text of a reply, when the front streams it (voice/both)."""

    message_id: str
    text: str


@dataclass(frozen=True)
class AssistantReply:
    display_text: str
    speech_text: str | None
    mode: str
    message_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    interrupted: bool = False


@dataclass(frozen=True)
class DelegationStarted:
    """The front handed a task to the worker while composing the reply `message_id`."""

    message_id: str
    mode: str


@dataclass(frozen=True)
class AssistantWait:
    text: str


@dataclass(frozen=True)
class TaskProgress:
    task_id: str
    tool: str
    step: int


@dataclass(frozen=True)
class NeedsConfirmation:
    task_id: str
    confirmation_id: str
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Notice:
    text: str


@dataclass(frozen=True)
class TaskEvent:
    """One orchestrator (or configuration) event, secrets already redacted."""

    task_id: str
    parent_id: str | None
    type: str
    payload: dict[str, Any]
    seq: int
    ts: str


ChannelMessage = (
    UserAccepted
    | AssistantDelta
    | AssistantSpeechDelta
    | AssistantReply
    | DelegationStarted
    | AssistantWait
    | TaskProgress
    | NeedsConfirmation
    | Notice
    | TaskEvent
)


@runtime_checkable
class Channel(Protocol):
    async def send(self, message: ChannelMessage) -> None: ...
