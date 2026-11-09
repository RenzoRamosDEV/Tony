import json
import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tony.core.music.ports import MusicError, Status, Track

IPC_TIMEOUT_SECONDS = 5.0
_NOTHING_PLAYING = "No hay nada reproduciéndose."


def spawn_detached(argv: list[str]) -> None:
    subprocess.Popen(  # noqa: S603 - argv list, never a shell
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class MpvBackend:
    """Drives a headless mpv over its JSON IPC socket, starting it on demand."""

    def __init__(
        self,
        socket_path: Path,
        spawn: Callable[[list[str]], None] = spawn_detached,
        find_binary: Callable[[], str | None] = lambda: shutil.which("mpv"),
        wait_seconds: float = 5.0,
        poll_seconds: float = 0.05,
    ) -> None:
        self._socket_path = socket_path
        self._spawn = spawn
        self._find_binary = find_binary
        self._wait_seconds = wait_seconds
        self._poll_seconds = poll_seconds

    def load(self, track: Track) -> None:
        self._ensure_running()
        self._send("playlist-clear")
        self._send("loadfile", track.url, "replace", -1, _title_option(track))
        self._send("set_property", "pause", False)

    def append(self, track: Track) -> None:
        self._ensure_running()
        self._send("loadfile", track.url, "append-play", -1, _title_option(track))

    def pause(self) -> None:
        self._require_playing()
        self._send("set_property", "pause", True)

    def resume(self) -> None:
        self._require_playing()
        self._send("set_property", "pause", False)

    def next(self) -> None:
        self._require_playing()
        if self._get("playlist-pos") + 1 >= self._get("playlist-count"):
            raise MusicError("No hay más canciones en la cola.")
        self._send("playlist-next")

    def previous(self) -> None:
        self._require_playing()
        if self._get("playlist-pos") <= 0:
            raise MusicError("No hay canción anterior.")
        self._send("playlist-prev")

    def set_volume(self, level: int) -> None:
        self._require_playing()
        self._send("set_property", "volume", level)

    def stop(self) -> None:
        self._require_playing()
        self._send("stop")

    def status(self) -> Status | None:
        if not self._alive() or self._get("idle-active"):
            return None
        return Status(
            title=self._get("media-title"),
            paused=self._get("pause"),
            volume=round(self._get("volume")),
            position=self._get("time-pos", default=None),
            duration=self._get("duration", default=None),
        )

    def _require_playing(self) -> None:
        if not self._alive() or self._get("idle-active"):
            raise MusicError(_NOTHING_PLAYING)

    def _ensure_running(self) -> None:
        if self._alive():
            return
        binary = self._find_binary()
        if binary is None:
            raise MusicError("mpv no está instalado: instala mpv")
        self._socket_path.unlink(missing_ok=True)
        self._spawn(
            [
                binary,
                "--no-video",
                "--idle=yes",
                "--no-terminal",
                "--audio-client-name=Tony",
                f"--input-ipc-server={self._socket_path}",
            ]
        )
        self._wait_until_alive()

    def _wait_until_alive(self) -> None:
        deadline = time.monotonic() + self._wait_seconds
        while not self._alive():
            if time.monotonic() >= deadline:
                raise MusicError("mpv no respondió al arrancar.")
            time.sleep(self._poll_seconds)

    def _alive(self) -> bool:
        try:
            self._connect().close()
        except OSError:
            return False
        return True

    def _connect(self) -> socket.socket:
        connection = socket.socket(socket.AF_UNIX)
        connection.settimeout(IPC_TIMEOUT_SECONDS)
        try:
            connection.connect(str(self._socket_path))
        except OSError:
            connection.close()
            raise
        return connection

    def _get(self, name: str, **fallback: Any) -> Any:
        try:
            return self._send("get_property", name)
        except MusicError:
            if "default" in fallback:
                return fallback["default"]
            raise

    def _send(self, *command: Any) -> Any:
        request = json.dumps({"command": list(command), "request_id": 1}) + "\n"
        try:
            with self._connect() as connection, connection.makefile("rwb") as stream:
                stream.write(request.encode())
                stream.flush()
                return _read_answer(stream)
        except OSError:
            raise MusicError("no pude hablar con mpv.") from None


def _read_answer(stream: Any) -> Any:
    for line in stream:
        answer = json.loads(line)
        if answer.get("request_id") != 1:
            continue
        if answer["error"] != "success":
            raise MusicError(f"mpv: {answer['error']}")
        return answer.get("data")
    raise MusicError("mpv cerró la conexión.")


def _title_option(track: Track) -> str:
    # mpv's %N%value form keeps commas and other separators in the title intact.
    return f"force-media-title=%{len(track.title.encode())}%{track.title}"
