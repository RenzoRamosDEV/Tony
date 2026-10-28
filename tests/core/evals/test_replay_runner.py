"""Replay runners reproduce recorded fixtures without calling any tool (specs/evals)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes.sinks import ListEventSink
from tony.core.evals.replay import FixtureMissing, ReplayConversationRunner, ReplayRunner
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import TaskRequest, TaskResult

SPEC = AgentSpec(name="viernes", role="worker", model="claude-sonnet", path=Path("/v"))
RESULT = {
    "status": "ok",
    "resumen": "Hay 3 ficheros .md",
    "datos": None,
    "pasos": [],
    "errores": [],
}
EVENTS = [
    ("task.queued", {"objetivo": "lista", "parent_id": None}),
    ("task.running", {}),
    ("mcp.status", {"filesystem": {"state": "ready"}}),
    ("task.started", {"agent": "viernes", "objetivo": "lista"}),
    ("tool.call", {"tool": "filesystem.list_directory", "args": {"path": "."}}),
    ("task.progress", {"tool": "filesystem.list_directory", "step": 1}),
    (
        "tool.result",
        {"tool": "filesystem.list_directory", "ok": True, "duration_ms": 3, "error": None},
    ),
    ("assistant.text", {"text": "Hecho"}),
    ("task.finished", {"status": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}}),
    ("task.result", {"result": RESULT}),
]


def write_fixture(path: Path, events=EVENTS) -> Path:
    lines = [
        json.dumps(
            {"schema_version": 1, "ts": "t", "task_id": "x", "seq": i, "type": t, "payload": p}
        )
        for i, (t, p) in enumerate(events, 1)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def test_replay_runner_reemits_runner_events_and_returns_the_recorded_result(
    tmp_path: Path,
) -> None:
    runner = ReplayRunner(write_fixture(tmp_path / "fs-list-md.jsonl"))
    sink = ListEventSink()

    result = await runner.run(SPEC, TaskRequest(objetivo="lista"), ToolCatalog.empty(), sink)

    assert result == TaskResult.model_validate(RESULT)
    assert sink.types() == [
        "task.started",
        "tool.call",
        "tool.result",
        "assistant.text",
        "task.finished",
    ]
    assert sink.payloads("tool.call") == [
        {"tool": "filesystem.list_directory", "args": {"path": "."}}
    ]


async def test_replay_runner_without_result_line_fails_naming_the_fixture(tmp_path: Path) -> None:
    runner = ReplayRunner(write_fixture(tmp_path / "x.jsonl", EVENTS[:-1]))

    with pytest.raises(FixtureMissing, match="task.result"):
        await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), ListEventSink())


def test_missing_fixture_names_the_path_and_how_to_record_it(tmp_path: Path) -> None:
    with pytest.raises(FixtureMissing) as info:
        ReplayRunner(tmp_path / "fs-x.jsonl")

    message = str(info.value)
    assert str(tmp_path / "fs-x.jsonl") in message
    assert "TONY_EVALS=1" in message and "tony replay" in message and "--to-eval fs-x" in message


def test_invalid_fixture_line_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type": "a", "payload": {}}\nno json\n', encoding="utf-8")

    with pytest.raises(FixtureMissing, match="línea 2"):
        ReplayRunner(path)


CONVERSATION = [
    {
        "turn": 1,
        "user": "hola",
        "delegate": None,
        "task_result": None,
        "reply": {"display_text": "Hola, señor.", "speech_text": None},
    },
    {
        "turn": 2,
        "user": "lista mis notas",
        "delegate": {"objetivo": "lista los .md", "contexto": "", "restricciones": []},
        "task_result": RESULT,
        "reply": {"display_text": "Tienes 3 notas.", "speech_text": "Tres notas"},
    },
]


class Handlers:
    def __init__(self) -> None:
        self.requests: list[TaskRequest] = []

    async def delegate(self, request: TaskRequest) -> TaskResult:
        self.requests.append(request)
        return TaskResult.model_validate(RESULT)


async def test_replay_conversation_delegates_only_when_recorded(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in CONVERSATION) + "\n", encoding="utf-8")
    runner = ReplayConversationRunner(path)
    handlers = Handlers()
    await runner.open(SPEC, ToolCatalog.empty(), handlers, ListEventSink())

    first = await runner.turn("<preamble>hola")
    second = await runner.turn("<preamble>lista mis notas")

    assert first.structured == {"display_text": "Hola, señor.", "speech_text": None}
    assert first.text == "Hola, señor."
    assert second.structured["display_text"] == "Tienes 3 notas."
    assert handlers.requests == [TaskRequest(objetivo="lista los .md")]
    assert runner.task_results() == {"lista los .md": TaskResult.model_validate(RESULT)}
    assert runner.session_id == "replay"
    await runner.interrupt()
    await runner.close()


async def test_replay_conversation_beyond_the_recorded_turns_fails(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps(CONVERSATION[0]) + "\n", encoding="utf-8")
    runner = ReplayConversationRunner(path)
    await runner.open(SPEC, ToolCatalog.empty(), Handlers(), ListEventSink())
    await runner.turn("hola")

    with pytest.raises(FixtureMissing, match="turno 2"):
        await runner.turn("otra")


async def test_blank_lines_are_skipped_and_unknown_types_ignored(tmp_path: Path) -> None:
    path = write_fixture(tmp_path / "x.jsonl")
    path.write_text(path.read_text(encoding="utf-8").replace("\n", "\n\n", 1), encoding="utf-8")
    runner = ReplayRunner(path)
    sink = ListEventSink()

    await runner.run(SPEC, TaskRequest(objetivo="o"), ToolCatalog.empty(), sink)

    assert "mcp.status" not in sink.types() and "task.queued" not in sink.types()
    assert len(runner.events) == len(EVENTS)


async def test_replay_conversation_without_delegate_never_calls_handlers(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps(CONVERSATION[0]) + "\n", encoding="utf-8")
    runner = ReplayConversationRunner(path)
    handlers = Handlers()
    await runner.open(SPEC, ToolCatalog.empty(), handlers, ListEventSink())

    turn = await runner.turn("hola")

    assert handlers.requests == [] and runner.task_results() == {}
    assert turn.text == "Hola, señor."


async def test_reply_without_display_text_is_empty_and_fixture_name_is_in_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps({"turn": 1, "user": "u", "reply": {"speech_text": None}}) + "\n")
    runner = ReplayConversationRunner(path)
    await runner.open(SPEC, ToolCatalog.empty(), Handlers(), ListEventSink())

    assert (await runner.turn("u")).text == ""
    with pytest.raises(FixtureMissing, match=str(path)):
        await runner.turn("otra")
