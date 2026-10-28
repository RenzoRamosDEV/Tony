"""RecordingConversationRunner writes one fixture line per turn (specs/evals)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes.conversation import FakeConversationRunner
from tests.fakes.sinks import ListEventSink
from tony.core.evals.recorder import RecordingConversationRunner
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.front_prompt import PREAMBLE_END, PREAMBLE_START

SPEC = AgentSpec(name="jarvis", role="front", model="claude-haiku", path=Path("/j"))
RESULT = TaskResult(status="ok", resumen="3 ficheros")


class Handlers:
    async def delegate(self, request: TaskRequest) -> TaskResult:
        return RESULT

    async def remember(self, text: str) -> str:
        return text

    async def set_reply_mode(self, mode: str) -> str:
        return mode


async def delegating(prompt: str, handlers) -> dict:
    result = await handlers.delegate(TaskRequest(objetivo="lista los .md"))
    return {"display_text": f"Tienes {result.resumen}.", "speech_text": "Tres"}


async def test_each_turn_is_written_with_user_delegate_result_and_reply(tmp_path: Path) -> None:
    inner = FakeConversationRunner(["Hola, señor.", delegating])
    path = tmp_path / "runs" / "listar-notas.jsonl"
    recorder = RecordingConversationRunner(inner, path)
    await recorder.open(SPEC, ToolCatalog.empty(), Handlers(), ListEventSink())
    preamble = f"{PREAMBLE_START}\nFecha y hora: x\n{PREAMBLE_END}\n\n"

    first = await recorder.turn(preamble + "hola")
    second = await recorder.turn(preamble + "lista mis notas")

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {
        "turn": 1,
        "user": "hola",
        "delegate": None,
        "task_result": None,
        "reply": {"display_text": "Hola, señor.", "speech_text": None},
    }
    assert lines[1]["turn"] == 2 and lines[1]["user"] == "lista mis notas"
    assert lines[1]["delegate"] == {
        "objetivo": "lista los .md",
        "contexto": "",
        "restricciones": [],
    }
    assert lines[1]["task_result"] == RESULT.model_dump()
    assert lines[1]["reply"] == {"display_text": "Tienes 3 ficheros.", "speech_text": "Tres"}
    assert first.text == "Hola, señor." and second.structured["speech_text"] == "Tres"
    assert recorder.session_id == "fake-session"
    assert inner.prompts[0] == preamble + "hola"


async def test_interrupt_and_close_reach_the_inner_runner(tmp_path: Path) -> None:
    inner = FakeConversationRunner([])
    recorder = RecordingConversationRunner(inner, tmp_path / "x.jsonl")

    await recorder.interrupt()
    await recorder.close()

    assert inner.interrupts == 1 and inner.closed is True


async def test_prompt_without_preamble_is_the_user_text_and_handlers_are_proxied(
    tmp_path: Path,
) -> None:
    remembered: list[str] = []

    class Remembering(Handlers):
        async def remember(self, text: str) -> str:
            remembered.append(text)
            return "ok"

    async def remembering_turn(prompt: str, handlers) -> str:
        return await handlers.remember("corto")

    recorder = RecordingConversationRunner(
        FakeConversationRunner([remembering_turn, "x"]), tmp_path / "r.jsonl"
    )
    await recorder.open(SPEC, ToolCatalog.empty(), Remembering(), ListEventSink())

    await recorder.turn("sin preámbulo")
    await recorder.turn(f"{PREAMBLE_END}\n\nsegundo")

    lines = [json.loads(line) for line in (tmp_path / "r.jsonl").read_text().splitlines()]
    assert remembered == ["corto"]
    assert [line["user"] for line in lines] == ["sin preámbulo", "segundo"]
    assert [line["turn"] for line in lines] == [1, 2]
    assert lines[0]["reply"] == {"display_text": "ok", "speech_text": None}
    assert lines[1]["delegate"] is None and lines[1]["task_result"] is None


async def test_open_forwards_catalog_and_resume_and_writes_into_nested_dirs(tmp_path: Path) -> None:
    inner = FakeConversationRunner(["x"])
    recorder = RecordingConversationRunner(inner, tmp_path / "a" / "b" / "r.jsonl")
    catalog = ToolCatalog.empty()

    await recorder.open(SPEC, catalog, Handlers(), ListEventSink(), resume="s-1")
    await recorder.turn("hola ñ")

    assert inner.resumes == ["s-1"] and inner.opened == [SPEC]
    text = (tmp_path / "a" / "b" / "r.jsonl").read_text(encoding="utf-8")
    assert '"user": "hola ñ"' in text and "\\u00f1" not in text


async def test_reopening_the_recorder_replaces_the_previous_run(tmp_path: Path) -> None:
    from tony.core.evals.replay import ReplayConversationRunner

    path = tmp_path / "runs" / "listar-notas.jsonl"
    first = RecordingConversationRunner(FakeConversationRunner(["primera", "x"]), path)
    await first.open(SPEC, ToolCatalog.empty(), Handlers(), ListEventSink())
    await first.turn("hola")
    await first.turn("otra")
    second = RecordingConversationRunner(FakeConversationRunner(["segunda"]), path)
    await second.open(SPEC, ToolCatalog.empty(), Handlers(), ListEventSink())
    await second.turn("hola")

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(line["turn"], line["reply"]["display_text"]) for line in lines] == [(1, "segunda")]
    replay = ReplayConversationRunner(path)
    await replay.open(SPEC, ToolCatalog.empty(), Handlers(), ListEventSink())
    assert (await replay.turn("hola")).text == "segunda"
