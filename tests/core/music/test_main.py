import os
from pathlib import Path

from tony.core.music.__main__ import default_socket_path


def test_socket_lives_in_xdg_runtime_dir():
    assert default_socket_path({"XDG_RUNTIME_DIR": "/run/user/1000"}) == Path(
        "/run/user/1000/tony-mpv.sock"
    )


def test_socket_falls_back_to_the_user_runtime_dir_by_uid():
    assert default_socket_path({}) == Path(f"/run/user/{os.getuid()}/tony-mpv.sock")
