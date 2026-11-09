from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from tests.apps.test_cli_chat import DONE, NO_PIN_POLICY, paced
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.changes import FakeChanges
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.apps.cli.main import create_app
from tony.core.config.placeholders import SecretMasker
from tony.core.guard.confirm import ConsoleLines
from tony.core.memory.history import HistoryStore

START = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def home(tmp_path):
    return make_tony_home(tmp_path, policy=NO_PIN_POLICY)[0]


def seed(home, *conversations):
    """conversations: (id, text, ...) tuples; each id is written one minute after the previous."""
    moment = {"now": START}
    store = HistoryStore(home, SecretMasker(), clock=lambda: moment["now"])
    for conversation_id, *texts in conversations:
        for text in texts:
            store.add(conversation_id, "user", "jarvis", text)
        moment["now"] += timedelta(minutes=1)
    store.close()


def stored(home, conversation_id):
    store = HistoryStore(home, SecretMasker())
    try:
        return [message.content for message in store.recent(conversation_id)]
    finally:
        store.close()


def run(home, *args):
    return CliRunner().invoke(create_app(), list(args), env={"TONY_HOME": str(home)})


def data_rows(result):
    return [line.split() for line in result.stdout.splitlines()[1:]]


def test_list_prints_the_table_newest_first(home):
    seed(home, ("a", "primera", "segunda"), ("b", "otra"))

    result = run(home, "conversations", "list")

    assert result.exit_code == 0
    header, first, second = result.stdout.splitlines()
    assert header.split() == ["id", "title", "messages", "last"]
    assert first.split()[:3] == ["b", "otra", "1"]
    assert second.split()[:3] == ["a", "primera", "2"]
    assert "2026-11-01" in second


def test_list_without_conversations_prints_only_the_header(home):
    result = run(home, "conversations", "list")

    assert result.exit_code == 0
    assert result.stdout.split() == ["id", "title", "messages", "last"]


def test_search_prints_matching_conversations(home):
    seed(home, ("a", "Compra de CAFÉ"), ("b", "otra cosa"))

    result = run(home, "conversations", "search", "café")

    assert result.exit_code == 0
    assert [row[0] for row in data_rows(result)] == ["a"]


def test_search_without_matches_prints_only_the_header(home):
    seed(home, ("a", "algo"))

    result = run(home, "conversations", "search", "zzz")

    assert result.exit_code == 0
    assert result.stdout.split() == ["id", "title", "messages", "last"]


def test_delete_removes_only_that_conversation(home):
    seed(home, ("a", "uno"), ("b", "dos"))

    result = run(home, "conversations", "delete", "a")

    assert result.exit_code == 0
    assert "a" in result.stdout
    assert stored(home, "a") == [] and stored(home, "b") == ["dos"]


def test_delete_unknown_id_exits_2_and_removes_nothing(home):
    seed(home, ("a", "uno"))

    result = run(home, "conversations", "delete", "nope")

    assert result.exit_code == 2
    assert result.stderr.startswith("tony:") and "nope" in result.stderr
    assert stored(home, "a") == ["uno"]


def chat(home, lines, *options, engine=None, worker=None):
    chat_engine = engine or FakeChatEngine()
    app = create_app(
        engine_factory=lambda: worker or FakeModelEngine([Final(structured=DONE)]),
        wording_factory=None,
        chat_engine_factory=lambda: chat_engine,
        console_factory=lambda: ConsoleLines(lines),
        getpass=lambda prompt: "",
        change_stream_factory=FakeChanges(),
    )
    result = CliRunner().invoke(app, ["chat", *options], env={"TONY_HOME": str(home)})
    return result, chat_engine


def test_resume_by_id_continues_that_conversation(home):
    seed(home, ("a", "pregunta vieja"), ("b", "otra"))

    result, engine = chat(home, paced("sigamos"), "--resume", "a")

    assert result.exit_code == 0
    assert stored(home, "a") == ["pregunta vieja", "sigamos", "ok"]
    assert "pregunta vieja" in engine.prompts[0]
    assert stored(home, "b") == ["otra"]


def test_bare_resume_continues_the_most_recent_conversation(home):
    seed(home, ("a", "vieja"), ("b", "nueva"))

    result, _ = chat(home, paced("sigamos"), "--resume")

    assert result.exit_code == 0
    assert stored(home, "b") == ["nueva", "sigamos", "ok"]
    assert stored(home, "a") == ["vieja"]


def test_resume_unknown_id_exits_2_without_starting_the_chat(home):
    result, engine = chat(home, paced("hola"), "--resume", "nope")

    assert result.exit_code == 2
    assert result.stderr.startswith("tony:") and "nope" in result.stderr
    assert engine.prompts == []


def test_bare_resume_without_conversations_exits_2(home):
    result, engine = chat(home, paced("hola"), "--resume")

    assert result.exit_code == 2
    assert result.stderr.startswith("tony:")
    assert engine.prompts == []


def test_chat_without_resume_starts_a_new_conversation(home):
    seed(home, ("a", "vieja"))

    result, engine = chat(home, paced("hola"))

    assert result.exit_code == 0
    assert "vieja" not in engine.prompts[0]
    assert stored(home, "a") == ["vieja"]


def test_permissions_are_asked_again_after_resume(home):
    seed(home, ("a", "borra a.md", "sí, adelante"))
    engine = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Borra a.md"}), Say("Hecho")])
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=DONE)]
    )

    result, _ = chat(
        home, paced("Borra a.md", 0.3, "s"), "--resume", "a", engine=engine, worker=worker
    )

    assert "Edith: Acción: " in result.stderr


def test_bare_resume_before_another_option_does_not_swallow_it(home):
    result, engine = chat(home, paced("hola"), "--resume", "--help")

    assert result.exit_code == 0
    assert "Usage" in result.stdout
    assert engine.prompts == []
