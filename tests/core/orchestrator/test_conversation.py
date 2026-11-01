import json

import pytest

from tests.core.orchestrator.tony_home import make_tony_home, set_config
from tests.fakes.fake_chat import Fail, FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.pin import FakePinPrompt
from tony.core.config.placeholders import SecretMasker
from tony.core.config.settings import load_config
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import Auth
from tony.core.guard.session import EdithSession, SessionGate
from tony.core.memory.history import HistoryStore
from tony.core.memory.preferences import PREFERENCES_FILE
from tony.core.orchestrator.agents import resolve_slots
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.runner import RunDeps

CONTROL = ["tony.delegate", "tony.remember", "tony.set_reply_mode"]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def home(tmp_path):
    return make_tony_home(tmp_path)[0]


def make(home, chat, *, worker=None, pin_required=False, clock=None):
    published = []
    config = load_config(home)
    session = EdithSession(
        Auth(pin_required=pin_required), PinStore(home), monotonic=clock or Clock()
    )
    deps = RunDeps(
        root=home,
        engine=worker or FakeModelEngine([Final(structured={"resumen": "hecho"})]),
        environ={},
        publish=published.append,
    )
    history = HistoryStore(home, SecretMasker())
    conversation = Conversation(
        slots=resolve_slots(home, config),
        config=config,
        deps=deps,
        chat_engine=chat,
        gate=SessionGate(session, FakePinPrompt(), timeout_s=1),
        history=history,
        conversation_id="c1",
    )
    return conversation, published, history, session


def types(published):
    return [event["type"] for event in published]


def write_prefs(home, text):
    (home / "memory").mkdir(exist_ok=True)
    (home / PREFERENCES_FILE).write_text(text)


async def test_streamed_reply_publishes_tokens_then_the_turn_result(home):
    chat = FakeChatEngine([Say("Buenas", " tardes, señor.")])
    conversation, published, *_ = make(home, chat)

    await conversation.handle("Hola")

    assert types(published) == ["token", "token", "result"]
    assert [(e["agent"], e["text"]) for e in published[:2]] == [
        ("jarvis", "Buenas"),
        ("jarvis", " tardes, señor."),
    ]
    result = published[2]
    assert (result["scope"], result["agent"], result["text"], result["reply_mode"]) == (
        "turn",
        "jarvis",
        "Buenas tardes, señor.",
        "auto",
    )
    assert chat.model_ids == ["claude-haiku-5-5"]


async def test_bundled_jarvis_is_offered_exactly_the_control_tools(home):
    chat = FakeChatEngine()
    conversation, *_ = make(home, chat)

    await conversation.handle("Hola")

    assert sorted(chat.offered[0]) == CONTROL


async def test_system_prompt_appends_masked_preferences_read_every_turn(home):
    (home / "config").mkdir()
    (home / "config" / ".env").write_text("SECRET_WORD=s3cr3t\n")
    chat = FakeChatEngine()
    conversation, *_ = make(home, chat)
    body = conversation.front.spec.system_prompt

    write_prefs(home, "- Llámame Renzo s3cr3t\n")
    await conversation.handle("uno")
    write_prefs(home, "- Prefiero respuestas cortas\n")
    await conversation.handle("dos")

    assert chat.system_prompts == [
        f"{body}\n\n## Preferencias del usuario\n- Llámame Renzo ***",
        f"{body}\n\n## Preferencias del usuario\n- Prefiero respuestas cortas",
    ]


@pytest.mark.parametrize("content", [None, "", "  \n"])
async def test_missing_or_empty_preferences_add_nothing(home, content):
    if content is not None:
        write_prefs(home, content)
    chat = FakeChatEngine()
    conversation, *_ = make(home, chat)

    await conversation.handle("Hola")

    assert chat.system_prompts == [conversation.front.spec.system_prompt]


async def test_first_message_has_no_history(home):
    chat = FakeChatEngine()
    conversation, *_ = make(home, chat)

    await conversation.handle("Hola")

    assert chat.prompts == ["<mensaje>\nHola\n</mensaje>"]


async def test_prompt_carries_the_last_20_messages_oldest_first(home):
    chat = FakeChatEngine()
    conversation, _, history, _ = make(home, chat)
    history.add("old", "user", "jarvis", "de otra conversación")
    for n in range(25):
        history.add("c1", "user" if n % 2 == 0 else "assistant", "jarvis", f"m{n}")

    await conversation.handle("nuevo")

    expected = "\n".join(f"{'usuario' if n % 2 == 0 else 'jarvis'}: m{n}" for n in range(5, 25))
    assert chat.prompts == [f"<historial>\n{expected}\n</historial>\n<mensaje>\nnuevo\n</mensaje>"]


async def test_user_and_assistant_rows_stored(home):
    conversation, _, history, _ = make(home, FakeChatEngine([Say("Buenas tardes, señor.")]))

    await conversation.handle("Hola")

    assert [(m.role, m.agent, m.content) for m in history.recent("c1")] == [
        ("user", "jarvis", "Hola"),
        ("assistant", "jarvis", "Buenas tardes, señor."),
    ]


@pytest.mark.parametrize(
    ("text", "sent", "mode"),
    [
        ("/t ¿qué hora es?", "¿qué hora es?", "text"),
        ("/v hola", "hola", "voice"),
        ("/t", "", "text"),
        ("/verdad", "/verdad", "voice"),
        ("/tx", "/tx", "voice"),
        ("hola /t", "hola /t", "voice"),
    ],
)
async def test_one_message_mode_prefix(home, text, sent, mode):
    write_prefs(home, "reply_mode: voice\n")
    chat = FakeChatEngine()
    conversation, published, history, _ = make(home, chat)

    await conversation.handle(text)

    assert chat.prompts[0].endswith(f"<mensaje>\n{sent}\n</mensaje>")
    assert published[-1]["reply_mode"] == mode
    assert history.recent("c1")[0].content == sent
    assert (home / PREFERENCES_FILE).read_text() == "reply_mode: voice\n"


async def test_mode_falls_back_to_the_config(home):
    set_config(home, "reply_mode: both\n")
    conversation, published, *_ = make(home, FakeChatEngine())

    await conversation.handle("Hola")

    assert published[-1]["reply_mode"] == "both"


async def test_engine_error_publishes_front_error_and_keeps_only_the_user_row(home):
    chat = FakeChatEngine([Fail(RuntimeError("model down"))], [Say("bien")])
    conversation, published, history, _ = make(home, chat)

    await conversation.handle("uno")
    await conversation.handle("dos")

    assert types(published) == ["error", "token", "result"]
    assert (published[0]["source"], published[0]["message"]) == ("front", "model down")
    assert [(m.role, m.content) for m in history.recent("c1")] == [
        ("user", "uno"),
        ("user", "dos"),
        ("assistant", "bien"),
    ]


async def test_session_touched_per_message_and_idle_relock_published(home):
    PinStore(home).set("4821")
    clock = Clock()
    conversation, published, _, session = make(
        home, FakeChatEngine(), pin_required=True, clock=clock
    )
    session.attempt("4821")

    await conversation.handle("uno")
    clock.now += 30 * 60
    await conversation.handle("dos")

    [auth] = [event for event in published if event["type"] == "auth"]
    assert (auth["state"], auth["reason"]) == ("locked", "idle")


async def test_delegate_runs_the_worker_and_returns_its_result(home):
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Lista"}), Say("Hecho")])
    worker = FakeModelEngine(
        [
            CallTool("filesystem.list_directory", {"path": "."}),
            Final(structured={"resumen": "Hay 1 nota", "datos": ["a.md"]}),
        ]
    )
    conversation, published, *_ = make(home, chat, worker=worker)

    await conversation.handle("Lista mis notas")

    assert json.loads(chat.replies[0].text)["datos"] == ["a.md"]
    assert not any(name.startswith("tony.") for name in worker.offered)
    assert "task_started" in types(published) and "token" not in types(published)[:-2]


async def test_viernes_as_front_gets_control_and_own_tools_judged(tmp_path):
    home, _ = make_tony_home(tmp_path)
    set_config(home, "front: viernes\n")
    chat = FakeChatEngine([CallTool("filesystem.read_file", {"path": "a.md"}), Say("leído")])
    conversation, *_ = make(home, chat)

    await conversation.handle("Lee a.md")

    assert set(CONTROL) <= set(chat.offered[0])
    assert "filesystem.read_file" in chat.offered[0]
    assert chat.replies[0].text == "# Nota A\nComprar pan."
    [line] = [json.loads(raw) for raw in (home / "logs" / "audit.jsonl").read_text().splitlines()]
    assert (line["agent"], line["tool"], line["verdict"]) == (
        "viernes",
        "filesystem.read_file",
        "allow",
    )
