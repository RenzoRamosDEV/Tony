from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from tony.core.events.core_events import ReplyMode
from tony.core.guard.broker import ConfirmDecision


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SendMessage(_Command):
    type: Literal["send_message"] = "send_message"
    text: str


class Confirm(_Command):
    type: Literal["confirm"] = "confirm"
    task_id: str
    decision: ConfirmDecision


class Cancel(_Command):
    type: Literal["cancel"] = "cancel"


class SetMode(_Command):
    type: Literal["set_mode"] = "set_mode"
    mode: ReplyMode


class Unlock(_Command):
    type: Literal["unlock"] = "unlock"
    pin: str | None = Field(repr=False)


class Stop(_Command):
    type: Literal["stop"] = "stop"


Command = Annotated[
    SendMessage | Confirm | Cancel | SetMode | Unlock | Stop, Field(discriminator="type")
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
