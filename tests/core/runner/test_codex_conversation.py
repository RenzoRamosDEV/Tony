"""`CodexCliConversation`: the `ConversationRunner` for `codex_cli` (`tony chat`).

Driven against the fake `codex` binary: the first turn opens a session and captures
its `session_id`; the next turn resumes it (`codex exec resume <id>`). Voice streaming
degrades to "no partial chunks, speak once at the end" (design.md Non-Goals): `on_speech`
is called exactly once per turn, after the full reply, never incrementally.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from tests.fakes.fake_codex import write_script
from tony.core.config import load_settings
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner.codex_conversation import CodexCliConversation

FAKE_CODEX = [sys.executable, "-m", "tests.fakes.fake_codex"]


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
