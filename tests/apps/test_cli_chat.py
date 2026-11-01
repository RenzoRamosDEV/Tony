import time

import pytest
from typer.testing import CliRunner

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.fake_chat import Fail, FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.apps.cli.main import create_app
from tony.core.guard.confirm import ConsoleLines
from tony.core.guard.pin import PinStore

PIN = "4821"
DONE = {"resumen": "hecho", "datos": None, "pasos": [], "errores": []}
NO_PIN_POLICY = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def paced(*items):
    """Console lines; a number pauses the reader that many seconds, a callable until it is true."""
    for item in items:
        if isinstance(item, int | float):
            time.sleep(item)
        elif callable(item):
            while not item():
                time.sleep(0.01)
        else:
            yield f"{item}\n"


def invoke(home, lines, chat, worker=None, pins=()):
    entered = list(pins)
    getpass_prompts = []

    def getpass(prompt):
        getpass_prompts.append(prompt)
        return entered.pop(0) if entered else ""

    app = create_app(
        engine_factory=lambda: worker or FakeModelEngine([Final(structured=DONE)]),
        wording_factory=None,
        chat_engine_factory=lambda: chat,
        console_factory=lambda: ConsoleLines(lines),
        getpass=getpass,
    )
    result = CliRunner().invoke(app, ["chat"], env={"TONY_HOME": str(home)})
    return result, getpass_prompts


def home_with(tmp_path, policy=NO_PIN_POLICY):
    return make_tony_home(tmp_path, policy=policy)[0]


def test_one_exchange_and_end_of_input(tmp_path):
    result, _ = invoke(
        home_with(tmp_path), paced("Hola"), FakeChatEngine([Say("Buenas tardes, señor.")])
    )

    assert result.exit_code == 0
    assert "Jarvis: Buenas tardes, señor.\n" in result.stdout


def test_streamed_chunks_form_one_line(tmp_path):
    chat = FakeChatEngine([Say("Buenas", " tardes")])

    result, _ = invoke(home_with(tmp_path), paced("Hola"), chat)

    assert "Jarvis: Buenas tardes\n" in result.stdout


def test_salir_ends_the_chat(tmp_path):
    chat = FakeChatEngine([Say("uno")], [Say("dos")])

    result, _ = invoke(home_with(tmp_path), paced("Hola", "/salir", "otra"), chat)

    assert result.exit_code == 0
    assert chat.prompts == ["<mensaje>\nHola\n</mensaje>"]


def test_empty_lines_are_ignored(tmp_path):
    chat = FakeChatEngine()

    invoke(home_with(tmp_path), paced("", "   ", "Hola"), chat)

    assert len(chat.prompts) == 1


def test_engine_error_is_reported_and_the_chat_continues(tmp_path):
    chat = FakeChatEngine([Fail(RuntimeError("model down"))], [Say("Aquí estoy.")])

    result, _ = invoke(home_with(tmp_path), paced("uno", "dos"), chat)

    assert result.exit_code == 0
    assert "tony: model down" in result.stderr
    assert "Jarvis: Aquí estoy.\n" in result.stdout


def delegating_chat():
    return FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Lista"}), Say("Listo.")])


def delegate_reply(chat):
    return chat.replies[0].text


def test_correct_pin_at_start_unlocks_delegation(tmp_path):
    home = home_with(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)
    chat = delegating_chat()

    result, prompts = invoke(home, paced("Lista mis notas"), chat, pins=[PIN])

    assert len(prompts) == 1
    assert '"resumen":"hecho"' in delegate_reply(chat)
    assert PIN not in result.output


def test_empty_pin_enters_conversation_only_mode(tmp_path):
    home = home_with(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)
    chat = delegating_chat()

    result, _ = invoke(home, paced("Lista mis notas"), chat, pins=[""])

    assert result.exit_code == 0
    assert delegate_reply(chat) == '{"error": "locked"}'
    assert "Jarvis: Listo." in result.stdout


def test_missing_lock_file_explains_tony_pin_set(tmp_path):
    home = home_with(tmp_path, SHIPPED_POLICY_YAML)
    chat = delegating_chat()

    result, prompts = invoke(home, paced("Lista"), chat)

    assert prompts == []
    assert "tony pin set" in result.stderr
    assert delegate_reply(chat) == '{"error": "locked"}'


def test_pin_command_asks_again(tmp_path):
    home = home_with(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)
    chat = FakeChatEngine(
        [Say("Sin delegar.")], [CallTool("tony.delegate", {"objetivo": "x"}), Say("Ya.")]
    )

    result, prompts = invoke(home, paced("Hola", "/pin", "Lista"), chat, pins=["", PIN])

    assert len(prompts) == 2
    assert '"resumen":"hecho"' in delegate_reply(chat)


def test_confirmed_delete_shows_the_edith_prefix(tmp_path):
    home, notes = make_tony_home(tmp_path, policy=NO_PIN_POLICY)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Borra a.md"}), Say("Borrada.")])
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=DONE)]
    )

    result, _ = invoke(home, paced("Borra a.md", 0.3, "s"), chat, worker)

    assert "Edith: Acción: " in result.stderr
    assert not (notes / "a.md").exists()


def test_line_after_a_confirmation_timeout_goes_to_the_front_agent(tmp_path):
    policy = NO_PIN_POLICY.replace("confirm_timeout_s: 60", "confirm_timeout_s: 0.2")
    home, notes = make_tony_home(tmp_path, policy=policy)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Borra a.md"}), Say("No pudo.")])
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=DONE)]
    )

    audited = (home / "logs" / "audit.jsonl").exists

    result, _ = invoke(home, paced("Borra a.md", audited, "Hola"), chat, worker)

    assert (notes / "a.md").exists()
    assert "sin respuesta" in chat.replies[0].text
    assert chat.prompts[1].endswith("<mensaje>\nHola\n</mensaje>")
    assert result.exit_code == 0


def test_invalid_agent_fails_at_start(tmp_path):
    home = home_with(tmp_path)
    agent_md = home / "agents" / "jarvis" / "agent.md"
    agent_md.write_text(agent_md.read_text().replace("role: front", "role: helper"))

    result, _ = invoke(home, paced("Hola"), FakeChatEngine())

    assert result.exit_code != 0
    assert "agents/jarvis/agent.md" in result.stderr
