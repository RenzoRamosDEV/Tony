from tests.fakes.music import FakeBackend, FakeResolver
from tony.core.music.player import MusicPlayer
from tony.core.music.ports import Track
from tony.core.music.server import build_server

EXPECTED_TOOLS = {
    "music_search",
    "music_play",
    "music_queue",
    "music_pause",
    "music_resume",
    "music_next",
    "music_previous",
    "music_volume",
    "music_now_playing",
    "music_stop",
}


def make_server():
    resolver = FakeResolver({"queen": Track("Queen", "https://s/q")})
    backend = FakeBackend()
    return build_server(MusicPlayer(resolver, backend)), backend


async def text_of(server, name, arguments):
    result = await server.call_tool(name, arguments)
    return result.content[0].text


async def test_exposes_exactly_the_music_tools():
    server, _ = make_server()

    assert {tool.name for tool in await server.list_tools()} == EXPECTED_TOOLS


async def test_play_tool_uses_spanish_argument_name():
    server, backend = make_server()

    assert await text_of(server, "music_play", {"consulta": "queen"}) == "Reproduciendo: Queen"
    assert backend.calls[0][0] == "load"


async def test_queue_tool():
    server, backend = make_server()

    assert "cola" in await text_of(server, "music_queue", {"consulta": "queen"})
    assert backend.calls[0][0] == "append"


async def test_volume_tool_validates_bounds_as_plain_text_error():
    server, backend = make_server()

    result = await text_of(server, "music_volume", {"nivel": 101})

    assert result == "Error: el volumen debe estar entre 0 y 100."
    assert backend.calls == []


async def test_parameterless_tools_reach_the_player():
    server, backend = make_server()

    for name in ("music_pause", "music_resume", "music_next", "music_previous", "music_stop"):
        await text_of(server, name, {})

    assert [call[0] for call in backend.calls] == ["pause", "resume", "next", "previous", "stop"]


async def test_now_playing_tool_when_idle():
    server, _ = make_server()

    assert await text_of(server, "music_now_playing", {}) == "No hay nada sonando."


async def test_search_tool_answers_the_title_and_never_plays():
    server, backend = make_server()

    assert await text_of(server, "music_search", {"consulta": "queen"}) == "Encontrada: Queen"
    assert backend.calls == []
