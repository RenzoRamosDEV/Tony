from tests.fakes.music import FakeBackend, FakeResolver
from tony.core.music.player import (
    MAX_RESOLVED_TRACKS,
    RESOLVED_TRACK_TTL_S,
    MusicPlayer,
)
from tony.core.music.ports import Track

QUEEN = Track(title="Bohemian Rhapsody", url="https://stream/queen-1")
QUEEN_REFRESHED = Track(title="Bohemian Rhapsody", url="https://stream/queen-2")
COVER = Track(title="Bohemian Rhapsody (Cover)", url="https://stream/cover")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SequenceResolver(FakeResolver):
    """Answers each query with its scripted tracks, one per call, in order."""

    def __init__(self, scripted):
        super().__init__()
        self.scripted = {query: list(tracks) for query, tracks in scripted.items()}

    def resolve(self, query):
        self.queries.append(query)
        return self.scripted[query].pop(0)


def make(scripted):
    resolver, backend, clock = SequenceResolver(scripted), FakeBackend(), Clock()
    return MusicPlayer(resolver, backend, clock=clock), resolver, backend, clock


def test_play_with_the_searched_title_does_not_search_again():
    player, resolver, backend, _ = make({"queen": [QUEEN]})

    assert player.search("queen") == "Encontrada: Bohemian Rhapsody"
    assert player.play("Bohemian Rhapsody") == "Reproduciendo: Bohemian Rhapsody"

    assert resolver.queries == ["queen"]
    assert backend.calls == [("load", QUEEN)]


def test_queue_with_the_searched_title_does_not_search_again():
    player, resolver, backend, _ = make({"queen": [QUEEN]})

    player.search("queen")
    player.queue("Bohemian Rhapsody")

    assert resolver.queries == ["queen"]
    assert backend.calls == [("append", QUEEN)]


def test_another_query_is_searched_normally():
    player, resolver, backend, _ = make({"queen": [QUEEN], "other": [COVER]})

    player.search("queen")
    player.play("other")

    assert resolver.queries == ["queen", "other"]
    assert backend.calls == [("load", COVER)]


def test_title_is_reusable_until_ten_minutes_exactly_minus_one_second():
    player, resolver, _, clock = make({"queen": [QUEEN]})
    player.search("queen")

    clock.now += RESOLVED_TRACK_TTL_S - 1
    player.play("Bohemian Rhapsody")

    assert resolver.queries == ["queen"]


def test_expired_track_is_resolved_again_and_plays_when_the_title_is_the_same():
    player, resolver, backend, clock = make(
        {"queen": [QUEEN], "Bohemian Rhapsody": [QUEEN_REFRESHED]}
    )
    player.search("queen")

    clock.now += RESOLVED_TRACK_TTL_S
    answer = player.play("Bohemian Rhapsody")

    assert answer == "Reproduciendo: Bohemian Rhapsody"
    assert resolver.queries == ["queen", "Bohemian Rhapsody"]
    assert backend.calls == [("load", QUEEN_REFRESHED)]


def test_refreshed_track_is_remembered_for_another_window():
    player, resolver, _, clock = make({"queen": [QUEEN], "Bohemian Rhapsody": [QUEEN_REFRESHED]})
    player.search("queen")
    clock.now += RESOLVED_TRACK_TTL_S
    player.play("Bohemian Rhapsody")

    clock.now += RESOLVED_TRACK_TTL_S - 1
    player.queue("Bohemian Rhapsody")

    assert resolver.queries == ["queen", "Bohemian Rhapsody"]


def test_expired_track_resolving_to_another_title_plays_nothing():
    player, _, backend, clock = make({"queen": [QUEEN], "Bohemian Rhapsody": [COVER]})
    player.search("queen")

    clock.now += RESOLVED_TRACK_TTL_S
    answer = player.play("Bohemian Rhapsody")

    assert answer.startswith("Error:")
    assert backend.calls == []


def test_expired_track_resolving_to_another_title_queues_nothing():
    player, _, backend, clock = make({"queen": [QUEEN], "Bohemian Rhapsody": [COVER]})
    player.search("queen")

    clock.now += RESOLVED_TRACK_TTL_S
    answer = player.queue("Bohemian Rhapsody")

    assert answer.startswith("Error:")
    assert backend.calls == []


def test_only_the_twenty_most_recent_tracks_are_kept():
    tracks = {f"q{i}": [Track(title=f"T{i}", url=f"u{i}")] for i in range(MAX_RESOLVED_TRACKS + 1)}
    tracks["T0"] = [Track(title="T0", url="u0-again")]
    player, resolver, _, _ = make(tracks)
    for i in range(MAX_RESOLVED_TRACKS + 1):
        player.search(f"q{i}")

    player.play("T1")
    assert resolver.queries[-1] == f"q{MAX_RESOLVED_TRACKS}"
    player.play("T0")

    assert resolver.queries[-1] == "T0"


def test_validity_is_ten_minutes_and_twenty_tracks():
    assert (RESOLVED_TRACK_TTL_S, MAX_RESOLVED_TRACKS) == (600.0, 20)


def test_searching_a_title_again_refreshes_its_recency():
    scripted = {f"q{i}": [Track(title=f"T{i}", url=f"u{i}")] for i in range(MAX_RESOLVED_TRACKS)}
    scripted["again"] = [Track(title="T0", url="u0-new")]
    scripted["last"] = [Track(title="Last", url="last")]
    player, resolver, _, _ = make(scripted)
    for i in range(MAX_RESOLVED_TRACKS):
        player.search(f"q{i}")
    player.search("again")
    player.search("last")

    player.play("T0")

    assert resolver.queries[-1] == "last"


def test_playing_a_new_query_does_not_remember_it_for_later():
    player, resolver, _, _ = make({"queen": [QUEEN, QUEEN], "Bohemian Rhapsody": [QUEEN]})

    player.play("queen")
    player.play("Bohemian Rhapsody")

    assert resolver.queries == ["queen", "Bohemian Rhapsody"]


def test_search_always_asks_the_resolver_even_for_a_remembered_title():
    player, resolver, _, _ = make({"queen": [QUEEN], "Bohemian Rhapsody": [QUEEN_REFRESHED]})
    player.search("queen")

    player.search("Bohemian Rhapsody")

    assert resolver.queries == ["queen", "Bohemian Rhapsody"]
