import pytest

from tony.core.orchestrator.commands import (
    AnswerClarification,
    Cancel,
    Confirm,
    DeleteConversation,
    InvalidCommand,
    Listen,
    Lock,
    ListConversations,
    ListDevices,
    ResumeConversation,
    SendMessage,
    SetAudioDevice,
    SetMode,
    Stop,
    StopListening,
    Unlock,
    parse_command,
)


def test_parses_list_devices():
    assert parse_command({"type": "list_devices"}) == ListDevices()


def test_parses_set_audio_device():
    cmd = parse_command({"type": "set_audio_device", "kind": "input", "device": "Mic A"})
    assert cmd == SetAudioDevice(kind="input", device="Mic A")


def test_parses_set_audio_device_with_null_device_as_system_default():
    cmd = parse_command({"type": "set_audio_device", "kind": "output", "device": None})
    assert cmd.device is None


def test_rejects_set_audio_device_with_bad_kind():
    with pytest.raises(InvalidCommand):
        parse_command({"type": "set_audio_device", "kind": "sideways", "device": None})


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
        ({"type": "lock"}, Lock()),
        (
            {"type": "send_message", "text": "Hola", "origin": "voice"},
            SendMessage(text="Hola", origin="voice"),
        ),
        (
            {"type": "send_message", "text": "Hola", "origin": "text"},
            SendMessage(text="Hola"),
        ),
        ({"type": "listen"}, Listen()),
        ({"type": "stop_listening"}, StopListening()),
        ({"type": "list_conversations"}, ListConversations()),
        ({"type": "resume_conversation", "id": "c1"}, ResumeConversation(id="c1")),
        ({"type": "delete_conversation", "id": "c1"}, DeleteConversation(id="c1")),
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
        ({"type": "listen", "purpose": "message"}, "listen"),
        ({"type": "stop_listening", "now": True}, "stop_listening"),
        ({"type": "resume_conversation"}, "resume_conversation"),
        ({"type": "delete_conversation"}, "delete_conversation"),
        ({"type": "resume_conversation", "id": 7}, "resume_conversation"),
        ({"type": "list_conversations", "limit": 1}, "list_conversations"),
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


def test_send_message_origin_defaults_to_text():
    assert parse_command({"type": "send_message", "text": "Hola"}).origin == "text"


def test_invalid_origin_names_send_message_and_origin():
    with pytest.raises(InvalidCommand) as raised:
        parse_command({"type": "send_message", "text": "Hola", "origin": "telepathy"})

    assert raised.value.command_type == "send_message"
    assert "origin" in str(raised.value)


def test_missing_conversation_id_names_the_field():
    with pytest.raises(InvalidCommand) as raised:
        parse_command({"type": "resume_conversation"})

    assert "id" in str(raised.value)


def test_confirm_approval_id_is_optional():
    assert (
        parse_command({"type": "confirm", "task_id": "t", "decision": "allow"}).approval_id is None
    )


def test_confirm_accepts_an_approval_id():
    command = parse_command(
        {"type": "confirm", "task_id": "t", "decision": "allow", "approval_id": "A1"}
    )

    assert command == Confirm(task_id="t", decision="allow", approval_id="A1")


def test_confirm_still_rejects_unknown_fields():
    with pytest.raises(InvalidCommand, match="extra"):
        parse_command({"type": "confirm", "task_id": "t", "decision": "allow", "extra": 1})


def test_parses_answer_clarification():
    command = parse_command({"type": "answer_clarification", "request_id": "r1", "answer": "sí"})

    assert command == AnswerClarification(request_id="r1", answer="sí")


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ({"type": "answer_clarification", "request_id": "r1"}, "answer"),
        ({"type": "answer_clarification", "answer": "x"}, "request_id"),
        ({"type": "answer_clarification", "request_id": "r1", "answer": 5}, "answer"),
    ],
)
def test_invalid_answer_clarification_names_the_field(raw, field):
    with pytest.raises(InvalidCommand) as raised:
        parse_command(raw)

    assert "answer_clarification" in str(raised.value) and field in str(raised.value)


def test_answer_clarification_error_never_echoes_the_answer():
    raw = {"type": "answer_clarification", "request_id": "r1", "answer": "hunter2", "x": "hunter2"}

    with pytest.raises(InvalidCommand) as raised:
        parse_command(raw)

    assert "hunter2" not in str(raised.value)


def test_answer_clarification_rejects_extra_fields():
    with pytest.raises(InvalidCommand, match="extra"):
        parse_command(
            {"type": "answer_clarification", "request_id": "r", "answer": "a", "extra": 1}
        )


def test_send_message_rejects_routine_origin():
    with pytest.raises(Exception) as raised:
        parse_command({"type": "send_message", "text": "Hola", "origin": "routine"})

    assert "origin" in str(raised.value)
