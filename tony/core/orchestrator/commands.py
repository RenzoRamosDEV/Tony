from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from tony.core.events.core_events import Origin, ReplyMode
from tony.core.guard.broker import ConfirmDecision


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SendMessage(_Command):
    type: Literal["send_message"] = "send_message"
    text: str
    origin: Origin = "text"


class Confirm(_Command):
    type: Literal["confirm"] = "confirm"
    task_id: str
    decision: ConfirmDecision
    approval_id: str | None = None


class AnswerClarification(_Command):
    type: Literal["answer_clarification"] = "answer_clarification"
    request_id: str
    answer: str


class Cancel(_Command):
    type: Literal["cancel"] = "cancel"


class SetMode(_Command):
    type: Literal["set_mode"] = "set_mode"
    mode: ReplyMode


class Unlock(_Command):
    type: Literal["unlock"] = "unlock"
    pin: str | None = Field(repr=False)


class Lock(_Command):
    type: Literal["lock"] = "lock"


class Listen(_Command):
    type: Literal["listen"] = "listen"


class StopListening(_Command):
    type: Literal["stop_listening"] = "stop_listening"


class Stop(_Command):
    type: Literal["stop"] = "stop"


class ListDevices(_Command):
    type: Literal["list_devices"] = "list_devices"


class SetAudioDevice(_Command):
    type: Literal["set_audio_device"] = "set_audio_device"
    kind: Literal["input", "output"]
    device: str | None


class ListConversations(_Command):
    type: Literal["list_conversations"] = "list_conversations"


class ResumeConversation(_Command):
    type: Literal["resume_conversation"] = "resume_conversation"
    id: str


class DeleteConversation(_Command):
    type: Literal["delete_conversation"] = "delete_conversation"
    id: str


Command = Annotated[
    SendMessage
    | Confirm
    | AnswerClarification
    | Cancel
    | SetMode
    | Unlock
    | Lock
    | Listen
    | StopListening
    | Stop
    | ListDevices
    | SetAudioDevice
    | ListConversations
    | ResumeConversation
    | DeleteConversation,
    Field(discriminator="type"),
]
_COMMAND = TypeAdapter(Command)


class InvalidCommand(Exception):
    def __init__(self, command_type: str, problem: str) -> None:
        self.command_type = command_type
        super().__init__(f"invalid command '{command_type}': {problem}")


def parse_command(raw: Any) -> Command:
    """Validate a UI command. Errors name the type and field only, never the submitted values,
    so a PIN can not leak through an error event."""
    command_type = str(raw.get("type")) if isinstance(raw, dict) else "None"
    try:
        return _COMMAND.validate_python(raw)
    except ValidationError as error:
        first = error.errors(include_input=False, include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"][1:]) or "type"
        raise InvalidCommand(command_type, f"{location}: {first['msg']}") from None
