import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from tony.core.music.ports import MusicError, Track

TIMEOUT_SECONDS = 30
_INSTALL = "yt-dlp no está instalado: instala yt-dlp"


def find_ytdlp(
    which: Callable[[str], str | None] = shutil.which, home: Path | None = None
) -> str | None:
    found = which("yt-dlp")
    if found:
        return found
    local = (home or Path.home()) / ".local" / "bin" / "yt-dlp"
    return str(local) if local.is_file() else None


class YtDlpResolver:
    def __init__(
        self,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        find_binary: Callable[[], str | None] = find_ytdlp,
    ) -> None:
        self._run = run
        self._find_binary = find_binary

    def resolve(self, query: str) -> Track:
        binary = self._find_binary()
        if binary is None:
            raise MusicError(_INSTALL)
        result = self._search(binary, query)
        if result.returncode != 0:
            raise MusicError(f"yt-dlp falló: {_last_line(result.stderr)}")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            raise MusicError(f"no encontré nada para «{query}»")
        return Track(title=lines[0], url=lines[1])

    def _search(self, binary: str, query: str) -> subprocess.CompletedProcess:
        argv = [
            binary,
            "--no-warnings",
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "--print",
            "%(title)s",
            "--print",
            "urls",
            f"ytsearch1:{query}",
        ]
        try:
            return self._run(
                argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
            )
        except FileNotFoundError:
            raise MusicError(_INSTALL) from None
        except subprocess.TimeoutExpired:
            raise MusicError("yt-dlp tardó demasiado en buscar.") from None


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "sin detalles"
