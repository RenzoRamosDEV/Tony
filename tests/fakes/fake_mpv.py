"""In-process fake of mpv's JSON IPC server on a unix socket (a tiny playlist state machine)."""

import json
import re
import socket
import threading
from pathlib import Path


class FakeMpv:
    def __init__(self, path: Path):
        self.path = path
        self.playlist: list[dict] = []
        self.pos = -1
        self.pause = False
        self.volume = 100.0
        self.position: float | None = 12.5
        self.duration: float | None = 200.0
        self.commands: list[list] = []
        self._server: socket.socket | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(self.path))
        self._server.listen()
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self._stopped.set()
        if self._server:
            self._server.close()
        self.path.unlink(missing_ok=True)

    @property
    def idle(self) -> bool:
        return self.pos < 0

    @property
    def current(self) -> dict | None:
        return None if self.idle else self.playlist[self.pos]

    def _accept(self) -> None:
        while not self._stopped.is_set():
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        with client, client.makefile("rwb") as stream:
            for line in stream:
                request = json.loads(line)
                self.commands.append(request["command"])
                stream.write(b'{"event":"idle"}\n')
                answer = self._run(request["command"])
                answer["request_id"] = request.get("request_id", 0)
                stream.write(json.dumps(answer).encode() + b"\n")
                stream.flush()

    def _run(self, command: list) -> dict:
        name, args = command[0], command[1:]
        if name == "loadfile":
            return self._loadfile(*args)
        if name == "playlist-clear":
            keep = [self.playlist[self.pos]] if not self.idle else []
            self.playlist, self.pos = keep, 0 if keep else -1
        elif name == "set_property":
            return self._set(*args)
        elif name == "get_property":
            return self._get(args[0])
        elif name == "playlist-next":
            self.pos += 1
        elif name == "playlist-prev":
            self.pos -= 1
        elif name == "stop":
            self.playlist, self.pos = [], -1
        else:
            return {"error": f"unknown command {name}"}
        return {"error": "success"}

    def _loadfile(self, url, mode="replace", index=-1, options="") -> dict:
        title = self._title(options)
        item = {"url": url, "title": title}
        if mode == "replace":
            self.playlist, self.pos = [item], 0
        else:
            self.playlist.append(item)
            if mode == "append-play" and self.idle:
                self.pos = len(self.playlist) - 1
        return {"error": "success"}

    @staticmethod
    def _title(options: str) -> str:
        match = re.fullmatch(r"force-media-title=%(\d+)%(.*)", options, re.S)
        assert match, f"unexpected loadfile options {options!r}"
        raw = match.group(2).encode()
        assert len(raw) >= int(match.group(1))
        return raw[: int(match.group(1))].decode()

    def _set(self, name, value) -> dict:
        if name not in ("pause", "volume"):
            return {"error": "property not found"}
        setattr(self, name, value)
        return {"error": "success"}

    def _get(self, name) -> dict:
        values = {
            "idle-active": self.idle,
            "pause": self.pause,
            "volume": self.volume,
            "playlist-pos": self.pos,
            "playlist-count": len(self.playlist),
        }
        if not self.idle:
            values |= {
                "media-title": self.current["title"],
                "time-pos": self.position,
                "duration": self.duration,
            }
        value = values.get(name)
        if name not in values or value is None:
            return {"error": "property unavailable"}
        return {"error": "success", "data": value}
