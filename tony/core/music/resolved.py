from collections import OrderedDict
from collections.abc import Callable

from tony.core.music.ports import MusicError, Resolver, Track

RESOLVED_TRACK_TTL_S = 600.0
MAX_RESOLVED_TRACKS = 20


class ResolvedTracks:
    """Tracks already found by title, so the one the user approved is the one that plays."""

    def __init__(
        self,
        resolver: Resolver,
        *,
        clock: Callable[[], float],
        ttl_s: float = RESOLVED_TRACK_TTL_S,
        capacity: int = MAX_RESOLVED_TRACKS,
    ) -> None:
        self._resolver = resolver
        self._clock = clock
        self._ttl_s = ttl_s
        self._capacity = capacity
        self._by_title: OrderedDict[str, tuple[Track, float]] = OrderedDict()

    def search(self, query: str) -> Track:
        return self._remember(self._resolver.resolve(query))

    def get(self, query: str) -> Track:
        """The remembered track titled `query`, else a plain (unremembered) resolution of it."""
        remembered = self._by_title.get(query)
        if remembered is None:
            return self._resolver.resolve(query)
        track, stored_at = remembered
        if self._clock() - stored_at < self._ttl_s:
            return track
        return self._refresh(track)

    def _refresh(self, expired: Track) -> Track:
        track = self._resolver.resolve(expired.title)
        if track.title != expired.title:
            raise MusicError(f"la canción «{expired.title}» ya no está disponible tal cual.")
        return self._remember(track)

    def _remember(self, track: Track) -> Track:
        self._by_title[track.title] = (track, self._clock())
        self._by_title.move_to_end(track.title)
        while len(self._by_title) > self._capacity:
            self._by_title.popitem(last=False)
        return track
