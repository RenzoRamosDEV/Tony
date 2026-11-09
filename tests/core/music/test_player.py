import pytest

from tests.fakes.music import FakeBackend, FakeResolver
from tony.core.music.player import MAX_QUERY_LENGTH, MusicPlayer
from tony.core.music.ports import MusicError, Status, Track

QUEEN = Track(title="Bohemian Rhapsody", url="https://stream/queen")


def make(tracks=None, backend=None, resolver=None):
    resolver = resolver or FakeResolver({"bohemian rhapsody": QUEEN} if tracks is None else tracks)
    backend = backend or FakeBackend()
    return MusicPlayer(resolver, backend), resolver, backend


def test_play_resolves_then_loads_replacing_current():
    player, resolver, backend = make()

    assert player.play("bohemian rhapsody") == "Reproduciendo: Bohemian Rhapsody"
    assert backend.calls == [("load", QUEEN)]


def test_queue_resolves_then_appends():
    player, _, backend = make()

    assert player.queue("bohemian rhapsody") == "Añadida a la cola: Bohemian Rhapsody"
    assert backend.calls == [("append", QUEEN)]


def test_query_is_trimmed_and_control_characters_become_spaces():
    player, resolver, _ = make()

    player.play("  bohemian\n\trhapsody \x00")

    assert resolver.queries == ["bohemian rhapsody"]


@pytest.mark.parametrize("query", ["", "   ", "\n\t", "\x00"])
def test_empty_query_is_an_error_and_touches_nothing(query):
    player, resolver, backend = make()

    assert player.play(query) == "Error: la consulta está vacía."
    assert player.queue(query) == "Error: la consulta está vacía."
    assert resolver.queries == [] and backend.calls == []


def test_query_of_max_length_is_accepted_and_one_more_is_rejected():
    ok, too_long = "a" * MAX_QUERY_LENGTH, "a" * (MAX_QUERY_LENGTH + 1)
    player, resolver, backend = make(tracks={ok: QUEEN})

    assert player.play(ok).startswith("Reproduciendo")
    assert player.play(too_long) == (
        f"Error: la consulta es demasiado larga (máximo {MAX_QUERY_LENGTH} caracteres)."
    )
    assert resolver.queries == [ok]


def test_nothing_found_is_reported_and_nothing_is_loaded():
    player, _, backend = make(tracks={})

    assert player.play("zzz") == "Error: no encontré nada para «zzz»"
    assert backend.calls == []


@pytest.mark.parametrize("method", ["play", "queue"])
def test_resolver_missing_tool_error_is_returned_not_raised(method):
    resolver = FakeResolver(error=MusicError("yt-dlp no está instalado: instala yt-dlp"))
    player, _, _ = make(resolver=resolver)

    assert getattr(player, method)("x") == "Error: yt-dlp no está instalado: instala yt-dlp"


@pytest.mark.parametrize("method", ["play", "queue"])
def test_backend_error_is_returned_not_raised(method):
    backend = FakeBackend(error=MusicError("mpv no está instalado: instala mpv"))
    player, _, _ = make(backend=backend)

    assert getattr(player, method)("bohemian rhapsody") == (
        "Error: mpv no está instalado: instala mpv"
    )


@pytest.mark.parametrize(
    ("method", "call", "message"),
    [
        ("pause", "pause", "Pausado."),
        ("resume", "resume", "Reanudado."),
        ("next", "next", "Siguiente canción."),
        ("previous", "previous", "Canción anterior."),
        ("stop", "stop", "Reproducción detenida."),
    ],
)
def test_simple_controls_delegate_and_confirm(method, call, message):
    player, _, backend = make()

    assert getattr(player, method)() == message
    assert backend.calls == [(call,)]


@pytest.mark.parametrize("method", ["pause", "resume", "next", "previous", "stop"])
def test_simple_controls_return_backend_errors(method):
    backend = FakeBackend(error=MusicError("No hay nada reproduciéndose."))
    player, _, _ = make(backend=backend)

    assert getattr(player, method)() == "Error: No hay nada reproduciéndose."


@pytest.mark.parametrize("level", [0, 1, 50, 99, 100])
def test_volume_inside_bounds_is_applied(level):
    player, _, backend = make()

    assert player.set_volume(level) == f"Volumen al {level}%."
    assert backend.calls == [("set_volume", level)]


@pytest.mark.parametrize("level", [-1, 101, 1000])
def test_volume_outside_bounds_is_rejected_without_calling_backend(level):
    player, _, backend = make()

    assert player.set_volume(level) == "Error: el volumen debe estar entre 0 y 100."
    assert backend.calls == []


def test_now_playing_describes_title_pause_volume_and_position():
    status = Status(title="Bohemian Rhapsody", paused=False, volume=80, position=65.4, duration=355)
    player, _, _ = make(backend=FakeBackend(current=status))

    assert player.now_playing() == "Sonando: Bohemian Rhapsody | volumen 80% | 1:05 / 5:55"


def test_now_playing_marks_paused_and_tolerates_unknown_times():
    status = Status(title="Live", paused=True, volume=0, position=None, duration=None)
    player, _, _ = make(backend=FakeBackend(current=status))

    assert player.now_playing() == "Sonando: Live (en pausa) | volumen 0%"


def test_now_playing_when_idle_is_not_an_error():
    player, _, _ = make(backend=FakeBackend(current=None))

    assert player.now_playing() == "No hay nada sonando."


def test_now_playing_returns_backend_errors():
    backend = FakeBackend(error=MusicError("mpv no está instalado: instala mpv"))
    player, _, _ = make(backend=backend)

    assert player.now_playing() == "Error: mpv no está instalado: instala mpv"


def test_search_reports_the_found_title_without_touching_the_backend():
    player, resolver, backend = make()

    assert player.search("  bohemian rhapsody ") == "Encontrada: Bohemian Rhapsody"
    assert resolver.queries == ["bohemian rhapsody"]
    assert backend.calls == []


def test_search_nothing_found_is_reported_without_touching_the_backend():
    player, _, backend = make(tracks={})

    assert player.search("zzz") == "Error: no encontré nada para «zzz»"
    assert backend.calls == []


def test_search_missing_tool_error_is_returned_not_raised():
    resolver = FakeResolver(error=MusicError("yt-dlp no está instalado: instala yt-dlp"))
    player, _, backend = make(resolver=resolver)

    assert player.search("x") == "Error: yt-dlp no está instalado: instala yt-dlp"
    assert backend.calls == []


@pytest.mark.parametrize("query", ["", "   ", "\n\t", "x" * (MAX_QUERY_LENGTH + 1)])
def test_search_rejects_empty_or_oversized_query_without_resolving(query):
    player, resolver, backend = make()

    assert player.search(query).startswith("Error: la consulta")
    assert resolver.queries == []
    assert backend.calls == []
