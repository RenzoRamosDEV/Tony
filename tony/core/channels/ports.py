"""Channel port: typed messages the chat session sends to whatever faces the user."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AssistantReply:
    display_text: str
    speech_text: str | None
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


ChannelMessage = AssistantReply | AssistantWait | TaskProgress | NeedsConfirmation | Notice


@runtime_checkable
class Channel(Protocol):
    async def send(self, message: ChannelMessage) -> None: ...
