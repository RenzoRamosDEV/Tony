"""Tests for `tony chat` (specs/cli-chat) with fakes for the front, the worker and stdin."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.apps.cli_helpers import FakeManager, write_agent
from tests.fakes.conversation import FakeConversationRunner
from tests.fakes.scripted_runner import ScriptedRunner
from tests.fakes.stdin import FakeStdin
from tony.apps.cli import chat as chat_app
from tony.apps.cli import main
from tony.core.memory.conversations import ConversationStore
from tony.core.runner import TaskRequest, TaskResult

runner = CliRunner()


def write_front(agents_dir: Path, name: str = "jarvis", role: str = "front") -> None:
    write_agent(agents_dir, name, role, model="claude-haiku")
    tool_dir = agents_dir / name / "tool"
    tool_dir.mkdir(exist_ok=True)
    (tool_dir / "tool.json").write_text(
        json.dumps({"native": ["delegate", "remember", "set_reply_mode"]}), encoding="utf-8"
    )


async def delegating(prompt: str, handlers: Any) -> dict[str, Any]:
    result = await handlers.delegate(TaskRequest(objetivo="lista"))
    return {"display_text": f"Resultado: {result.resumen}", "speech_text": None}


@pytest.fixture
def cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_repo)
    write_front(tmp_repo / "agents")
    write_agent(tmp_repo / "agents", "viernes", "worker")
    state: dict[str, Any] = {
        "turns": [],
        "script": [],
        "stdin": ["/salir\n"],
        "runners": [],
        "conversations": [],
        "managers": [],
    }

    def conversation_factory(settings, gate, call):
        conversation = FakeConversationRunner(state["turns"])
        state["conversations"].append(conversation)
        return conversation

    def worker_runner_factory(settings, task_id, gate, call, token):
        scripted = ScriptedRunner(
            task_id, state["script"], cancel_token=token, gate=gate, call=call
        )
        state["runners"].append(scripted)
        return scripted

    def manager_factory(settings):
        manager = FakeManager()
        state["managers"].append(manager)
        return manager

    monkeypatch.setattr(main, "conversation_factory", conversation_factory)
    monkeypatch.setattr(main, "worker_runner_factory", worker_runner_factory)
    monkeypatch.setattr(main, "manager_factory", manager_factory)
    monkeypatch.setattr(main, "lines_factory", lambda: FakeStdin(state["stdin"]))
    return state


def invoke(*args: str):
    return runner.invoke(main.app, ["chat", *args])


def store() -> ConversationStore:
    return ConversationStore(Path("memory/conversations.sqlite"))


def test_chat_continues_the_last_cli_conversation(cli) -> None:
    previous = store()
    c1 = previous.start_conversation("cli")
    previous.close()
    cli["turns"] = ["Hola, señor."]
    cli["stdin"] = ["hola\n", "/salir\n"]

    result = invoke()

    assert result.exit_code == 0
    assert [m.content for m in store().recent_messages(c1)] == ["hola", "Hola, señor."]


def test_new_flag_starts_another_conversation(cli) -> None:
    previous = store()
    c1 = previous.start_conversation("cli")
    previous.close()
    cli["turns"] = ["Hola."]
    cli["stdin"] = ["hola\n", "/salir\n"]

    result = invoke("--new")

    assert result.exit_code == 0
    current = store()
    assert current.recent_messages(c1) == []
    assert current.last_conversation("cli") != c1
    assert [m.content for m in current.recent_messages(current.last_conversation("cli"))] == [
        "hola",
        "Hola.",
    ]


def test_agents_dir_and_config_are_respected(cli, tmp_path: Path) -> None:
    other = tmp_path / "agentes"
    write_front(other, "lunes")
    write_agent(other, "martes", "worker")
    config = tmp_path / "tony.yaml"
    config.write_text("front: lunes\nworker: martes\n", encoding="utf-8")

    result = invoke("--agents-dir", str(other), "--config", str(config))

    assert result.exit_code == 0
    assert cli["conversations"][0].opened[0].name == "lunes"


def test_front_with_mismatched_role_warns_and_continues(cli, tmp_repo: Path) -> None:
    (tmp_repo / "config" / "tony.yaml").write_text(
        "front: viernes\nworker: jarvis\n", encoding="utf-8"
    )
    cli["turns"] = ["Sigo aquí."]
    cli["stdin"] = ["hola\n", "/salir\n"]

    result = invoke()

    assert result.exit_code == 0
    assert "viernes" in result.stderr and "worker" in result.stderr and "front" in result.stderr
    assert "Sigo aquí." in result.stdout


def test_missing_front_exits_2_naming_it(cli, tmp_repo: Path) -> None:
    (tmp_repo / "config" / "tony.yaml").write_text("front: nadie\n", encoding="utf-8")

    result = invoke()

    assert result.exit_code == 2
    assert "nadie" in result.stderr
    assert cli["conversations"] == []


def test_text_reply_prints_only_display_text(cli) -> None:
    cli["turns"] = [{"display_text": "Hola", "speech_text": "Hola"}]
    cli["stdin"] = ["hola\n", "/salir\n"]

    result = invoke()

    assert "Hola" in result.stdout
    assert "🔊" not in result.stdout


def test_voice_reply_is_degraded_to_text_with_speaker_line(cli, tmp_repo: Path) -> None:
    (tmp_repo / "config" / "tony.yaml").write_text("reply_mode: voice\n", encoding="utf-8")
    cli["turns"] = [{"display_text": "# Informe\ntodo bien", "speech_text": "Informe listo"}]
    cli["stdin"] = ["informe\n", "/salir\n"]

    result = invoke()

    lines = result.stdout.splitlines()
    assert "🔊 Informe listo" in lines
    assert lines.index("# Informe") == lines.index("🔊 Informe listo") + 1


def test_progress_is_shown_as_a_dim_line_on_stderr(cli) -> None:
    cli["turns"] = [delegating]
    cli["script"] = [("tool", "filesystem.read_file", {"path": "a.md"})]
    cli["stdin"] = ["lee a.md\n", "/salir\n"]

    result = invoke()

    assert "· filesystem.read_file" in result.stderr
    assert "· filesystem.read_file" not in result.stdout
    assert "Resultado: guion completado" in result.stdout


CONFIRM_SCRIPT = [("confirm", "filesystem.move_file", {"source": "a", "destination": "b"})]
PROMPT = (
    'Viernes quiere ejecutar filesystem.move_file {"destination": "b", "source": "a"}. '
    "¿Confirmas? [s/N] "
)


@pytest.mark.parametrize("answer", ["Sí\n", "s\n", "SI\n"])
def test_affirmative_answer_approves_the_tool(cli, answer: str) -> None:
    cli["turns"] = [delegating]
    cli["script"] = CONFIRM_SCRIPT
    cli["stdin"] = ["mueve\n", answer, "/salir\n"]

    result = invoke()

    assert PROMPT in result.stderr
    assert "Resultado: guion completado" in result.stdout
    assert cli["runners"][0].state.steps == ["filesystem.move_file(a, b)"]


@pytest.mark.parametrize("answer", ["n\n", "\n", "yes\n"])
def test_other_answers_reject_and_cancel_the_task(cli, answer: str) -> None:
    cli["turns"] = [delegating]
    cli["script"] = CONFIRM_SCRIPT
    cli["stdin"] = ["mueve\n", answer, "/salir\n"]

    result = invoke()

    assert "Resultado: Tarea cancelada: el usuario no confirmó filesystem.move_file." in (
        result.stdout
    )
    assert cli["runners"][0].state.steps == []


def test_no_answer_within_timeout_cancels_and_the_session_continues(cli, tmp_repo: Path) -> None:
    (tmp_repo / "config" / "tony.yaml").write_text(
        "limits:\n  confirm_timeout_s: 0.1\n", encoding="utf-8"
    )
    cli["turns"] = [delegating, "Sigo aquí."]
    cli["script"] = CONFIRM_SCRIPT
    cli["stdin"] = ["mueve\n", 0.4, "hola\n", "/salir\n"]

    result = invoke()

    assert "falta de confirmación" in result.stderr
    assert "Resultado: Tarea cancelada: el usuario no confirmó filesystem.move_file." in (
        result.stdout
    )
    assert "Sigo aquí." in result.stdout
    assert result.exit_code == 0


def test_mode_command_shows_persisted_or_configured_mode(cli, tmp_repo: Path) -> None:
    cli["stdin"] = ["/mode\n", "/salir\n"]
    assert "auto" in invoke().stdout

    Path("memory").mkdir(exist_ok=True)
    Path("memory/settings.json").write_text('{"reply_mode": "text"}', encoding="utf-8")
    cli["stdin"] = ["/mode\n", "/salir\n"]

    result = invoke()

    assert "text" in result.stdout
    assert cli["conversations"][-1].prompts == []


def test_mode_command_persists_a_valid_mode(cli) -> None:
    cli["stdin"] = ["/mode voice\n", "/salir\n"]

    result = invoke()

    assert json.loads(Path("memory/settings.json").read_text()) == {"reply_mode": "voice"}
    assert "voice" in result.stdout


def test_mode_command_rejects_unknown_values_listing_the_valid_ones(cli) -> None:
    cli["stdin"] = ["/mode loud\n", "/salir\n"]

    result = invoke()

    for value in ("auto", "voice", "text", "both"):
        assert value in result.stderr
    assert not Path("memory/settings.json").exists()


def test_memoria_command_prints_the_preferences_file(cli) -> None:
    Path("memory").mkdir(exist_ok=True)
    Path("memory/preferences.md").write_text(
        "- [2026-10-28] Prefiere respuestas cortas\n- [2026-10-28] Llamarle señor\n",
        encoding="utf-8",
    )
    cli["stdin"] = ["/memoria\n", "/salir\n"]

    result = invoke()

    assert "- [2026-10-28] Prefiere respuestas cortas" in result.stdout
    assert "- [2026-10-28] Llamarle señor" in result.stdout
    assert cli["conversations"][0].prompts == []


def test_salir_exits_with_zero_and_closes_the_front(cli) -> None:
    cli["stdin"] = ["/salir\n"]

    result = invoke()

    assert result.exit_code == 0
    assert cli["conversations"][0].closed is True
    assert cli["managers"] == [] or all(m.stopped for m in cli["managers"])


def test_eof_exits_with_zero(cli) -> None:
    cli["stdin"] = [None]

    assert invoke().exit_code == 0


def test_unknown_command_warns_without_a_turn(cli) -> None:
    cli["stdin"] = ["/foo\n", "/salir\n"]

    result = invoke()

    assert "/foo" in result.stderr
    assert cli["conversations"][0].prompts == []


def test_cancel_without_an_active_task_warns(cli) -> None:
    cli["stdin"] = ["/cancel\n", "/salir\n"]

    result = invoke()

    assert "tarea activa" in result.stderr


def test_prefix_without_text_warns_without_a_turn(cli) -> None:
    cli["stdin"] = ["/t\n", "/salir\n"]

    result = invoke()

    assert "/t" in result.stderr
    assert cli["conversations"][0].prompts == []


def test_worker_secrets_from_the_environment_are_redacted_everywhere(
    cli, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_TOKEN", "env-token-secret-123")
    tool_dir = tmp_repo / "agents" / "viernes" / "tool"
    tool_dir.mkdir()
    (tool_dir / "tool.json").write_text(
        json.dumps(
            {"mcpServers": {"api": {"url": "https://x", "headers": {"X": "${WORKER_TOKEN}"}}}}
        ),
        encoding="utf-8",
    )
    sinks: list[Any] = []
    real_sink = chat_app.JsonlEventSink

    def recording_sink(logs_dir, task_id, secrets):
        sinks.append(list(secrets))
        return real_sink(logs_dir, task_id, secrets)

    monkeypatch.setattr(chat_app, "JsonlEventSink", recording_sink)
    cli["turns"] = [delegating]
    cli["script"] = [("result", TaskResult(status="ok", resumen="vale env-token-secret-123"))]
    cli["stdin"] = ["lista\n", "/salir\n"]

    result = invoke()

    assert "Resultado: vale ***" in result.stdout
    assert "env-token-secret-123" in sinks[0]
    rows = (
        sqlite3.connect("memory/conversations.sqlite")
        .execute("SELECT result_json FROM tasks")
        .fetchall()
    )
    assert "env-token-secret-123" not in rows[0][0]


def test_front_text_is_logged_in_a_chat_jsonl(cli) -> None:
    cli["turns"] = ["Hola, señor."]
    cli["stdin"] = ["hola\n", "/salir\n"]

    invoke()

    logs = list(Path("logs").glob("*/chat-*.jsonl"))
    assert len(logs) == 1
    assert logs[0].stem == f"chat-{store().last_conversation('cli')}"


def test_turn_is_saved_with_the_reply_mode(cli) -> None:
    cli["turns"] = ["Hola, señor."]
    cli["stdin"] = ["hola\n", "/salir\n"]

    invoke()

    current = store()
    messages = current.recent_messages(current.last_conversation("cli"))
    assert [(m.role, m.content, m.reply_mode) for m in messages] == [
        ("user", "hola", None),
        ("assistant", "Hola, señor.", "text"),
    ]


def test_user_text_and_prompt_go_to_stderr_not_stdout(cli) -> None:
    cli["turns"] = ["Hola."]
    cli["stdin"] = ["hola\n", "/salir\n"]

    result = invoke()

    assert "tú> " in result.stderr
    assert "tú> " not in result.stdout


def test_chat_help_is_in_spanish() -> None:
    result = runner.invoke(main.app, ["chat", "--help"])

    assert result.exit_code == 0
    for option, word in (
        ("--config", "configuración"),
        ("--agents-dir", "agentes"),
        ("--new", "conversación"),
    ):
        assert option in result.output
        assert word in result.output


def test_root_help_lists_chat_run_and_version() -> None:
    result = runner.invoke(main.app, ["--help"])

    assert "chat" in result.output and "run" in result.output and "version" in result.output
