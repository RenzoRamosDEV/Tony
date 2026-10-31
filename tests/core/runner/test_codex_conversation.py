"""`CodexCliConversation`: the `ConversationRunner` for `codex_cli` (`tony chat`).

Driven against the fake `codex` binary: the first turn opens a session and captures
its `session_id`; the next turn resumes it (`codex exec resume <id>`). Voice streaming
degrades to "no partial chunks, speak once at the end" (design.md Non-Goals): `on_speech`
is called exactly once per turn, after the full reply, never incrementally.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from tests.fakes.fake_codex import write_script
from tony.core.config import load_settings
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner.codex_conversation import NO_RESULT_EVENT, TURN_FAILED, CodexCliConversation

FAKE_CODEX = [sys.executable, "-m", "tests.fakes.fake_codex"]


@pytest.fixture(autouse=True)
def unused_gateway(monkeypatch):
    """Parser tests exercise the CLI subprocess without opening an unused tool socket."""
    monkeypatch.setattr(
        "tony.core.runner.codex_conversation.BridgeServer", lambda *args: nullcontext()
    )


class RecordingEvents:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type, payload) -> None:
        self.events.append((event_type, payload))


class NeverGate:
    async def confirm(self, request):
        return False


async def no_call(qualified, args, timeout):
    raise AssertionError("no debería llamar a ninguna tool en estos tests")


def make_spec() -> AgentSpec:
    return AgentSpec(name="jarvis", role="front", model="claude-sonnet", path=Path("/tmp/x"))


async def opened_conversation(script_path: Path) -> CodexCliConversation:
    settings = load_settings(None)
    conversation = CodexCliConversation(
        settings=settings,
        gate=NeverGate(),
        call=no_call,
        codex_command=[*FAKE_CODEX],
        env={"FAKE_CODEX_SCRIPT": str(script_path)},
    )
    await conversation.open(make_spec(), ToolCatalog(), handlers=None, events=RecordingEvents())
    return conversation


async def test_first_turn_opens_a_session_and_captures_its_id(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "sess-1", "result": {"display_text": "hola"}}],
    )
    conversation = await opened_conversation(script)

    turn = await conversation.turn("hola")

    assert turn.text == "hola"
    assert conversation.session_id == "sess-1"


async def test_the_second_turn_resumes_the_captured_session(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [
            {"session_id": "sess-1", "result": {"display_text": "primero"}},
            {"session_id": "sess-1", "result": {"display_text": "segundo"}},
        ],
    )
    conversation = await opened_conversation(script)

    await conversation.turn("uno")
    second = await conversation.turn("dos")

    assert second.text == "segundo"


async def test_on_speech_is_called_exactly_once_with_the_full_reply(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [
            {
                "session_id": "sess-1",
                "result": {"display_text": "hola", "speech_text": "hola hablado"},
            }
        ],
    )
    conversation = await opened_conversation(script)
    spoken: list[str] = []

    async def on_speech(text: str) -> None:
        spoken.append(text)

    await conversation.turn("hola", on_speech=on_speech)

    assert spoken == ["hola hablado"]


async def test_the_subprocess_never_inherits_this_process_stdin(
    tmp_path: Path, monkeypatch
) -> None:
    """A codex that unexpectedly reads stdin must not hang the turn on an inherited tty."""
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"display_text": "hola"}}],
    )
    conversation = await opened_conversation(script)
    captured: dict[str, object] = {}
    original = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        captured["stdin"] = kwargs.get("stdin")
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    await conversation.turn("hola")

    assert captured["stdin"] == asyncio.subprocess.DEVNULL


@pytest.mark.parametrize("source", ["agent_text", "stdout", "stderr"])
async def test_approval_block_is_reported_clearly(tmp_path: Path, monkeypatch, source: str) -> None:
    script = write_script(
        tmp_path / "script.json",
        [
            {
                "session_id": "s1",
                "agent_text": "MCP tool requires approval",
            }
        ],
    )
    runner = await opened_conversation(script)
    if source != "agent_text":

        async def blocked_process(*args, **kwargs):
            class Process:
                returncode = 1

                async def communicate(self):
                    message = b"MCP tool requires approval"
                    return (message, b"") if source == "stdout" else (b"", message)

            return Process()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", blocked_process)
    result = await runner.turn("hola")
    assert result.error is not None
    message = result.text
    if source == "agent_text":
        assert runner.session_id == "s1"
    assert "codex" in message.lower()
    assert "aprobación" in message
    assert "bloque" in message
    assert "esquema" not in message


@pytest.mark.parametrize(
    "final_text, expected",
    [
        (json.dumps({"display_text": "último"}), "último"),
        ("not JSON", "invalid"),
        ("{}", "invalid"),
        (None, "missing"),
    ],
)
async def test_real_event_stream_uses_last_agent_message(
    tmp_path: Path, final_text, expected
) -> None:
    events = [
        {"type": "thread.started", "thread_id": "real-thread"},
        {"type": "turn.started"},
    ]
    if final_text is not None:
        for text in [json.dumps({"display_text": "anterior"}), final_text]:
            events.append(
                {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
            )
    events.extend(
        [
            {"type": "item.completed", "item": {"type": "command_execution", "text": "ignore"}},
            {"type": "turn.completed", "usage": {}},
        ]
    )
    stdout = "noise\n" + "\n".join(json.dumps(event) for event in events)
    runner = await opened_conversation(tmp_path / "unused.json")
    result = await runner._finish_turn(stdout, None, None)
    assert runner.session_id == "real-thread"
    if expected == "último":
        assert result.text == expected
        assert result.error is None
    elif expected == "missing":
        assert result.error == NO_RESULT_EVENT
    else:
        assert result.error is not None
        assert result.text == TURN_FAILED.format(diagnostic=result.error)


async def test_codex_exposes_native_delegation_and_resumes_with_valid_sandbox_flags(
    tmp_path, monkeypatch
):
    from tony.core.loader import ToolConfig
    from tony.core.runner import TaskResult
    from tony.core.runner import codex_conversation as module

    requests = []
    bridge = {}

    class Handlers:
        async def delegate(self, request):
            requests.append(request)
            return TaskResult(status="ok", resumen="Done")

    class CaptureBridge:
        def __init__(self, path, dispatch):
            bridge["dispatch"] = dispatch

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(module, "BridgeServer", CaptureBridge)
    conversation = CodexCliConversation(load_settings(None), NeverGate(), no_call)
    front = make_spec().model_copy(update={"tools": ToolConfig(native=["delegate"])})
    await conversation.open(front, ToolCatalog(), Handlers(), RecordingEvents())
    arguments = []

    async def fake_process(argv):
        arguments.append(argv)
        reply = await bridge["dispatch"]("tony.delegate", {"objetivo": "Work"})
        assert "Done" in str(reply)
        return "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "session"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": '{"display_text":"Done"}'},
                    }
                ),
            ]
        ), ""

    monkeypatch.setattr(conversation, "_run_subprocess", fake_process)
    assert (await conversation.turn("first")).text == "Done"
    assert (await conversation.turn("second")).text == "Done"
    assert len(requests) == 2
    assert arguments[1].index("-s") < arguments[1].index("resume")
    assert arguments[1][arguments[1].index("resume") + 1] == "session"
