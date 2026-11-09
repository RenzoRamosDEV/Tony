import re
import time
from collections.abc import Callable

from tony.core.music.ports import MusicError, PlayerBackend, Resolver, Status
from tony.core.music.resolved import MAX_RESOLVED_TRACKS, RESOLVED_TRACK_TTL_S, ResolvedTracks

__all__ = ["MAX_QUERY_LENGTH", "MAX_RESOLVED_TRACKS", "RESOLVED_TRACK_TTL_S", "MusicPlayer"]

MAX_QUERY_LENGTH = 200
MIN_VOLUME, MAX_VOLUME = 0, 100
_CONTROL_RUN = re.compile(r"[\x00-\x1f\x7f]+")


class MusicPlayer:
    """Every method answers with text for the model: failures come back as `Error: ...`."""

    def __init__(
        self,
        resolver: Resolver,
        backend: PlayerBackend,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tracks = ResolvedTracks(resolver, clock=clock)
        self._backend = backend

    def play(self, query: str) -> str:
        return self._guarded(lambda: self._play(query))

    def queue(self, query: str) -> str:
        return self._guarded(lambda: self._queue(query))

    def search(self, query: str) -> str:
        return self._guarded(lambda: f"Encontrada: {self._tracks.search(_clean(query)).title}")

    def pause(self) -> str:
        return self._control(self._backend.pause, "Pausado.")

    def resume(self) -> str:
        return self._control(self._backend.resume, "Reanudado.")

    def next(self) -> str:
        return self._control(self._backend.next, "Siguiente canción.")

    def previous(self) -> str:
        return self._control(self._backend.previous, "Canción anterior.")

    def stop(self) -> str:
        return self._control(self._backend.stop, "Reproducción detenida.")

    def set_volume(self, level: int) -> str:
        if not MIN_VOLUME <= level <= MAX_VOLUME:
            return f"Error: el volumen debe estar entre {MIN_VOLUME} y {MAX_VOLUME}."
        return self._control(lambda: self._backend.set_volume(level), f"Volumen al {level}%.")

    def now_playing(self) -> str:
        return self._guarded(self._describe_current)

    def _play(self, query: str) -> str:
        track = self._tracks.get(_clean(query))
        self._backend.load(track)
        return f"Reproduciendo: {track.title}"

    def _queue(self, query: str) -> str:
        track = self._tracks.get(_clean(query))
        self._backend.append(track)
        return f"Añadida a la cola: {track.title}"

    def _describe_current(self) -> str:
        status = self._backend.status()
        return "No hay nada sonando." if status is None else _describe(status)

    def _control(self, action: Callable[[], None], done: str) -> str:

        def run() -> str:
            action()
            return done

        return self._guarded(run)

    @staticmethod
    def _guarded(action: Callable[[], str]) -> str:
        try:
            return action()
        except MusicError as error:
            return f"Error: {error}"


def _clean(query: str) -> str:
    cleaned = _CONTROL_RUN.sub(" ", query).strip()
    if not cleaned:
        raise MusicError("la consulta está vacía.")
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise MusicError(f"la consulta es demasiado larga (máximo {MAX_QUERY_LENGTH} caracteres).")
    return cleaned


def _describe(status: Status) -> str:
    paused = " (en pausa)" if status.paused else ""
    parts = [f"Sonando: {status.title}{paused}", f"volumen {status.volume}%"]
    if status.position is not None and status.duration is not None:
        parts.append(f"{_clock(status.position)} / {_clock(status.duration)}")
    return " | ".join(parts)


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"
