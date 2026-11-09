import os
from collections.abc import Mapping
from pathlib import Path

from tony.core.music.mpv import MpvBackend
from tony.core.music.player import MusicPlayer
from tony.core.music.server import build_server
from tony.core.music.ytdlp import YtDlpResolver

SOCKET_NAME = "tony-mpv.sock"


def default_socket_path(environ: Mapping[str, str] = os.environ) -> Path:
    runtime_dir = environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime_dir) / SOCKET_NAME


def main() -> None:
    player = MusicPlayer(YtDlpResolver(), MpvBackend(default_socket_path()))
    build_server(player).run("stdio")


if __name__ == "__main__":
    main()
