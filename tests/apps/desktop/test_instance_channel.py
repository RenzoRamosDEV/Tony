import pytest

from tony.apps.desktop.instance_channel import (
    CLIENT_TIMEOUT_MS,
    MAX_MESSAGE_BYTES,
    parse_message,
    socket_name,
)


def test_inside_flatpak_the_socket_lives_in_the_app_runtime_dir():
    environ = {"XDG_RUNTIME_DIR": "/run/user/1000", "FLATPAK_ID": "io.github.renzoramosdev.Tony"}
    assert socket_name(environ, uid=1000) == (
        "/run/user/1000/app/io.github.renzoramosdev.Tony/tony.sock"
    )


def test_outside_flatpak_the_socket_lives_in_the_runtime_dir():
    assert socket_name({"XDG_RUNTIME_DIR": "/run/user/1000"}, uid=1000) == (
        "/run/user/1000/tony-desktop.sock"
    )


@pytest.mark.parametrize("environ", [{}, {"XDG_RUNTIME_DIR": ""}, {"FLATPAK_ID": "x"}])
def test_without_runtime_dir_a_per_user_name_is_used(environ):
    assert socket_name(environ, uid=1000) == "tony-desktop-1000"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"show", "show"),
        (b"focus", "focus"),
        (b"show\n", "show"),
        (b"focus\n", "focus"),
        (b"record", None),
        (b"", None),
        (b"\n", None),
        (b"Show", None),
        (b" show", None),
        (b"show\nfocus", None),
        (b"focus\n\n", None),
        (b"\xff\xfe", None),
        (b"focus" + b" " * 11, None),
        (b"x" * 17, None),
    ],
)
def test_only_show_and_focus_are_accepted(raw, message):
    assert parse_message(raw) == message


def test_limits():
    assert (MAX_MESSAGE_BYTES, CLIENT_TIMEOUT_MS) == (16, 500)


def test_oversize_input_is_rejected_even_if_it_starts_with_a_message():
    assert parse_message(b"focus\n" + b"x" * 20) is None
