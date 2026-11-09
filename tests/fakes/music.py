from tony.core.music.ports import MusicError, Status, Track


class FakeResolver:
    def __init__(self, tracks: dict[str, Track] | None = None, error: MusicError | None = None):
        self.tracks = tracks or {}
        self.error = error
        self.queries: list[str] = []

    def resolve(self, query: str) -> Track:
        self.queries.append(query)
        if self.error:
            raise self.error
        if query not in self.tracks:
            raise MusicError(f"no encontré nada para «{query}»")
        return self.tracks[query]


class FakeBackend:
    """Records calls; `error` makes every call fail, `current` is what status() returns."""

    def __init__(self, error: MusicError | None = None, current: Status | None = None):
        self.error = error
        self.current = current
        self.calls: list[tuple] = []

    def _record(self, *call) -> None:
        self.calls.append(call)
        if self.error:
            raise self.error

    def load(self, track: Track) -> None:
        self._record("load", track)

    def append(self, track: Track) -> None:
        self._record("append", track)

    def pause(self) -> None:
        self._record("pause")

    def resume(self) -> None:
        self._record("resume")

    def next(self) -> None:
        self._record("next")

    def previous(self) -> None:
        self._record("previous")

    def set_volume(self, level: int) -> None:
        self._record("set_volume", level)

    def status(self) -> Status | None:
        self._record("status")
        return self.current

    def stop(self) -> None:
        self._record("stop")
