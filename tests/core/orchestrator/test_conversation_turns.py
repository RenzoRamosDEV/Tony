import pytest

from tests.core.orchestrator.test_conversation import make, set_config, write_prefs
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.fake_chat import CallTool, Fail, FakeChatEngine, Say


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def home(tmp_path):
    return make_tony_home(tmp_path)[0]


def started(published):
    turns = [e for e in published if e["type"] == "turn_started"]
    assert len(turns) == 1
    return {k: v for k, v in turns[0].items() if k != "ts"}


async def test_turn_started_precedes_the_first_token(home):
    conversation, published, *_ = make(home, FakeChatEngine([Say("Buenas", " tardes.")]))

    await conversation.handle("Hola")

    assert [e["type"] for e in published] == ["turn_started", "token", "token", "result"]


async def test_default_voice_ready_writes_and_does_not_speak(home):
    write_prefs(home, "reply_mode: voice\n")
    conversation, published, *_ = make(home, FakeChatEngine())

    await conversation.handle("Hola")

    assert started(published) == {
        "type": "turn_started",
        "agent": "jarvis",
        "origin": "text",
        "reply_mode": "voice",
        "speaks": False,
        "writes": True,
    }


@pytest.mark.parametrize(
    ("persisted", "text", "origin", "expected"),
    [
        ("auto", "Hola", "voice", ("voice", "auto", True, False)),
        ("auto", "Hola", "text", ("text", "auto", False, True)),
        ("both", "Hola", "text", ("text", "both", True, True)),
        ("text", "/v Hola", "text", ("text", "voice", True, False)),
        ("voice", "/t Hola", "voice", ("voice", "text", False, True)),
    ],
)
async def test_turn_started_carries_origin_applied_mode_and_plan(
    home, persisted, text, origin, expected
):
    write_prefs(home, f"reply_mode: {persisted}\n")
    conversation, published, *_ = make(home, FakeChatEngine(), voice_ready=lambda: True)

    await conversation.handle(text, origin=origin)

    event = started(published)
    assert (event["origin"], event["reply_mode"], event["speaks"], event["writes"]) == expected


async def test_voice_not_ready_writes(home):
    set_config(home, "reply_mode: voice\n")
    conversation, published, *_ = make(home, FakeChatEngine(), voice_ready=lambda: False)

    await conversation.handle("Hola", origin="voice")

    assert (started(published)["speaks"], started(published)["writes"]) == (False, True)


async def test_mode_changed_during_the_turn_keeps_the_turn_plan(home):
    write_prefs(home, "reply_mode: voice\n")
    chat = FakeChatEngine([CallTool("tony.set_reply_mode", {"mode": "text"}), Say("Hecho")])
    conversation, published, *_ = make(home, chat, voice_ready=lambda: True)

    await conversation.handle("Solo texto")

    event = started(published)
    assert (event["reply_mode"], event["speaks"], event["writes"]) == ("voice", True, False)
    assert published[-1]["reply_mode"] == "voice"
    assert conversation.reply_mode() == "text"


async def test_tokens_still_published_when_the_turn_does_not_write(home):
    write_prefs(home, "reply_mode: voice\n")
    chat = FakeChatEngine([Say("Buenas", " tardes.")])
    conversation, published, *_ = make(home, chat, voice_ready=lambda: True)

    await conversation.handle("Hola")

    assert started(published)["writes"] is False
    assert [e["text"] for e in published if e["type"] == "token"] == ["Buenas", " tardes."]


async def test_model_failure_still_announced_the_turn(home):
    conversation, published, *_ = make(home, FakeChatEngine([Fail()]))

    assert await conversation.handle("Hola") is None

    assert [e["type"] for e in published] == ["turn_started", "error"]
