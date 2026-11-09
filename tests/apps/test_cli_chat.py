import json
import time

import pytest
from typer.testing import CliRunner

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.skills_home import set_native
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.changes import FakeChanges
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


def invoke(home, lines, chat, worker=None, pins=(), changes=None):
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
        change_stream_factory=changes or FakeChanges(),
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


NO_READ_POLICY = NO_PIN_POLICY.replace(
    "rules:\n", 'rules:\n  - match: "filesystem.read_*"\n    verdict: deny\n    id: no-read\n', 1
)


def audit_rules(home):
    path = home / "logs" / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["rule"] for line in path.read_text().splitlines()]


def test_policy_edit_applies_to_the_next_call_in_chat(tmp_path):
    home = home_with(tmp_path)
    changes = FakeChanges()
    policy = home / "agents" / "edith" / "policy.yaml"

    def edit_policy():
        policy.write_text(NO_READ_POLICY)
        changes.push_from_thread(policy)
        return True

    read = CallTool("filesystem.read_file", {"path": "a.md"})
    worker = FakeModelEngine([read, Final(structured=DONE)])
    chat = FakeChatEngine(
        [CallTool("tony.delegate", {"objetivo": "Lee"}), Say("uno")],
        [CallTool("tony.delegate", {"objetivo": "Lee"}), Say("dos")],
    )
    lines = paced(
        "uno",
        lambda: len(audit_rules(home)) == 1,
        edit_policy,
        lambda: changes.handled == 1,
        "dos",
    )

    result, _ = invoke(home, lines, chat, worker=worker, changes=changes)

    assert result.exit_code == 0, result.output
    assert audit_rules(home) == ["filesystem.read_*/allow", "no-read"]
    assert changes.started == [(home, "edith")] and changes.stop.is_set()


def test_run_starts_no_watcher(tmp_path):
    home = home_with(tmp_path)
    changes = FakeChanges()
    app = create_app(
        engine_factory=lambda: FakeModelEngine([Final(structured=DONE)]),
        wording_factory=None,
        change_stream_factory=changes,
    )

    result = CliRunner().invoke(app, ["run", "viernes", "x"], env={"TONY_HOME": str(home)})

    assert result.exit_code == 0
    assert changes.started == []


def test_invalid_edits_keep_the_previous_config_in_chat(tmp_path):
    home = home_with(tmp_path)
    tool_json = home / "agents" / "viernes" / "tool" / "tool.json"
    tool_json.write_text(
        json.dumps({**json.loads(tool_json.read_text()), "native": ["read_skill"]})
    )
    changes = FakeChanges()
    policy = home / "agents" / "edith" / "policy.yaml"

    def break_files():
        policy.write_text("default: [roto\n")
        tool_json.write_text('{"mcpServers": {}, "confirm": []}')
        changes.push_from_thread(policy, tool_json)
        return True

    read = CallTool("filesystem.read_file", {"path": "a.md"})
    worker = FakeModelEngine([read, Final(structured=DONE)])
    delegate = [CallTool("tony.delegate", {"objetivo": "Lee"}), Say("ok")]
    chat = FakeChatEngine(delegate, delegate)
    lines = paced(
        "uno",
        lambda: len(audit_rules(home)) == 1,
        break_files,
        lambda: changes.handled == 1,
        "dos",
    )

    result, _ = invoke(home, lines, chat, worker=worker, changes=changes)

    assert result.exit_code == 0, result.output
    assert audit_rules(home) == ["filesystem.read_*/allow", "filesystem.read_*/allow"]
    assert "tony.read_skill" in worker.offered
    assert "tony: warning: agents/edith/policy.yaml" in result.stderr
    assert "tony: agents/viernes/tool/tool.json: confirm" in result.stderr


ASK = CallTool("tony.ask_user", {"question": "¿Qué cuenta?", "options": ["Personal", "Trabajo"]})
READ = CallTool("filesystem.read_file", {"path": "a.md"})
NOTE_SOURCE = {
    "connector": "filesystem",
    "id": "a.md",
    "title": "Nota A",
    "retrieved_at": "2026-11-01T09:00:00Z",
    "excerpt": "Comprar pan.",
}


def asking_home(tmp_path, policy=NO_PIN_POLICY):
    home, _ = make_tony_home(tmp_path, policy=policy)
    set_native(home, "viernes", ["ask_user"])
    return home


def delegating(*replies):
    return FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Manda"}), *replies])


def test_delegated_task_asks_and_a_number_selects_the_option(tmp_path):
    home = asking_home(tmp_path)
    worker = FakeModelEngine([ASK, Final(structured=DONE)])

    result, _ = invoke(home, paced("Manda", 0.5, "2"), delegating(Say("Listo.")), worker)

    assert result.exit_code == 0
    assert worker.replies[0].text == "Trabajo"
    assert "Viernes: ¿Qué cuenta?\n1) Personal\n2) Trabajo\n" in result.stderr
    assert "Viernes: ¿Qué cuenta?" not in result.stdout


def test_free_text_answer_reaches_the_tool_verbatim(tmp_path):
    home = asking_home(tmp_path)
    worker = FakeModelEngine([ASK, Final(structured=DONE)])

    invoke(home, paced("Manda", 0.5, "la de casa"), delegating(Say("Listo.")), worker)

    assert worker.replies[0].text == "la de casa"


def test_line_after_a_question_timeout_goes_to_the_front_agent(tmp_path):
    policy = NO_PIN_POLICY.replace("confirm_timeout_s: 60", "confirm_timeout_s: 0.2")
    home = asking_home(tmp_path, policy)
    worker = FakeModelEngine([ASK, Final(structured=DONE)])
    chat = delegating(Say("Sin respuesta."))

    audited = (home / "logs" / "audit.jsonl").exists

    result, _ = invoke(home, paced("Manda", audited, 0.5, "Hola"), chat, worker)

    assert worker.replies[0].text == "no answer from the user"
    assert chat.prompts[1].endswith("<mensaje>\nHola\n</mensaje>")
    assert result.exit_code == 0


def test_task_result_sources_are_printed_after_the_result(tmp_path):
    home = asking_home(tmp_path)
    cited = {**DONE, "datos": {"fuentes": [NOTE_SOURCE]}}
    worker = FakeModelEngine([READ, Final(structured=cited)])

    result, _ = invoke(home, paced("Manda"), delegating(Say("Listo.")), worker)

    assert "Fuentes:\n- filesystem · Nota A\n" in result.stdout


def test_invented_sources_are_not_printed(tmp_path):
    home = asking_home(tmp_path)
    invented = {**NOTE_SOURCE, "excerpt": "Comprar vino."}
    worker = FakeModelEngine([READ, Final(structured={**DONE, "datos": {"fuentes": [invented]}})])

    result, _ = invoke(home, paced("Manda"), delegating(Say("Listo.")), worker)

    assert "Fuentes:" not in result.stdout


def test_result_without_sources_prints_no_sources_block(tmp_path):
    home = asking_home(tmp_path)

    result, _ = invoke(home, paced("Manda"), delegating(Say("Listo.")))

    assert "Fuentes:" not in result.stdout and "Fuentes:" not in result.stderr
