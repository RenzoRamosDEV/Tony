import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.guard.previews import PREVIEW_FIELD_LIMIT, build_preview

MASKER = SecretMasker({"s3cr3t"})
ELLIPSIS = "…"


def preview(tool, args, masker=MASKER):
    return build_preview(tool, args, masker)


@pytest.mark.parametrize("tool", ["gmail.send_email", "gmail.draft_email"])
def test_email_fields(tool):
    args = {"to": "a@x.com", "cc": "b@x.com", "subject": "Hola", "body": "Texto", "x": 1}

    assert preview(tool, args) == {
        "to": "a@x.com",
        "cc": "b@x.com",
        "subject": "Hola",
        "body": "Texto",
    }


def test_absent_fields_are_omitted():
    assert preview("gmail.send_email", {"to": "a@x.com", "body": "b"}) == {
        "to": "a@x.com",
        "body": "b",
    }


def test_body_cut_at_the_limit_with_ellipsis():
    result = preview("gmail.send_email", {"body": "x" * 5000})

    assert result["body"] == "x" * PREVIEW_FIELD_LIMIT + ELLIPSIS
    assert PREVIEW_FIELD_LIMIT == 2000


def test_body_of_exactly_the_limit_is_not_cut():
    assert preview("gmail.send_email", {"body": "x" * 2000})["body"] == "x" * 2000


def test_body_one_over_the_limit_is_cut():
    assert preview("gmail.send_email", {"body": "x" * 2001})["body"] == "x" * 2000 + ELLIPSIS


def test_write_file_fields_with_utf8_size_of_uncut_content():
    content = "é" * 3000

    result = preview("filesystem.write_file", {"path": "/a.md", "content": content})

    assert result == {
        "path": "/a.md",
        "bytes": 6000,
        "content": "é" * 2000 + ELLIPSIS,
    }


def test_write_file_without_content_has_no_size():
    assert preview("filesystem.write_file", {"path": "/a.md"}) == {"path": "/a.md"}


def test_bytes_counts_the_unmasked_content():
    result = preview("filesystem.write_file", {"path": "p", "content": "s3cr3t"})

    assert result["bytes"] == 6
    assert result["content"] == "***"


@pytest.mark.parametrize("tool", ["google-calendar.create-event", "google-calendar.update-event"])
def test_calendar_fields_with_attendee_list(tool):
    args = {
        "summary": "Reunión",
        "start": "2026-11-10T10:00",
        "end": "2026-11-10T11:00",
        "attendees": ["a@x.com", "b@x.com"],
        "calendarId": "primary",
    }

    assert preview(tool, args) == {
        "summary": "Reunión",
        "start": "2026-11-10T10:00",
        "end": "2026-11-10T11:00",
        "attendees": '["a@x.com", "b@x.com"]',
    }


def test_secret_value_in_a_field_is_masked():
    assert preview("gmail.send_email", {"body": "clave s3cr3t"})["body"] == "clave ***"


def test_secret_straddling_the_cut_never_leaks_a_fragment():
    body = "x" * 1998 + "s3cr3t"

    assert preview("gmail.send_email", {"body": body})["body"] == "x" * 1998 + "**" + ELLIPSIS


def test_unknown_tool_previews_masked_json_of_args():
    result = preview("shell.run", {"cmd": "echo s3cr3t", "api_key": "abc"})

    assert result == {"args": '{"api_key": "***", "cmd": "echo ***"}'}


def test_unknown_tool_args_are_capped():
    result = preview("shell.run", {"cmd": "x" * 5000})

    assert len(result["args"]) == PREVIEW_FIELD_LIMIT + 1
    assert result["args"].endswith(ELLIPSIS)


def test_secret_named_key_inside_a_field_value_is_masked():
    attendees = [{"email": "a@x.com", "token": "abc"}]

    result = preview("google-calendar.create-event", {"attendees": attendees})

    assert result == {"attendees": '[{"email": "a@x.com", "token": "***"}]'}
