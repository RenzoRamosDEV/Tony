import pytest

from tony.core.orchestrator.commands import (
    Cancel,
    Confirm,
    InvalidCommand,
    SendMessage,
    SetMode,
    Stop,
    Unlock,
    parse_command,
)


@pytest.mark.parametrize(
    ("raw", "command"),
    [
        ({"type": "send_message", "text": "Hola"}, SendMessage(text="Hola")),
        (
            {"type": "confirm", "task_id": "t1", "decision": "always"},
            Confirm(task_id="t1", decision="always"),
        ),
        ({"type": "cancel"}, Cancel()),
        ({"type": "set_mode", "mode": "text"}, SetMode(mode="text")),
        ({"type": "unlock", "pin": "4821"}, Unlock(pin="4821")),
        ({"type": "unlock", "pin": None}, Unlock(pin=None)),
        ({"type": "stop"}, Stop()),
    ],
)
def test_valid_commands(raw, command):
    assert parse_command(raw) == command


@pytest.mark.parametrize(
    ("raw", "named"),
    [
        ({"type": "fly"}, "fly"),
        ({}, "None"),
        ({"type": "send_message"}, "send_message"),
        ({"type": "confirm", "task_id": "t1", "decision": "maybe"}, "confirm"),
        ({"type": "set_mode", "mode": "loud"}, "set_mode"),
        ({"type": "unlock"}, "unlock"),
        ("not a dict", "None"),
    ],
)
def test_invalid_commands_name_the_type(raw, named):
    with pytest.raises(InvalidCommand) as raised:
        parse_command(raw)

    assert raised.value.command_type == named
    assert f"'{named}'" in str(raised.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "unlock", "pin": 4821},
        {"type": "unlock", "pin": ["4821"]},
        {"type": "unlock", "pin": "4821", "extra": "4821"},
        {"type": "send_message", "text": "4821", "pin": "4821"},
    ],
)
def test_the_pin_never_appears_in_errors(raw):
    with pytest.raises(InvalidCommand) as raised:
        parse_command(raw)

    assert "4821" not in str(raised.value)


def test_unlock_repr_hides_the_pin():
    command = Unlock(pin="4821")

    assert "4821" not in repr(command) and "4821" not in str(command)
