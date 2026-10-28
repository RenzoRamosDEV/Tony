"""ClaudeSdkConversation over a fake persistent client (specs/front-agent: sesión)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from tests.core.runner_helpers import fake_catalog, result_message
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.config import load_settings
from tony.core.loader import AgentSpec, ToolConfig
from tony.core.mcp import ToolCatalog
from tony.core.runner.conversation import ClaudeSdkConversation, FrontTurn

STRUCTURED = {"display_text": "Hola, señor.", "speech_text": None}


class Handlers:
    async def delegate(self, request):
        raise NotImplementedError

    async def remember(self, text):
        return text

    async def set_reply_mode(self, mode):
        return mode


class FakeSessionClient:
    """ClaudeSDKClient stand-in: explicit connect/disconnect, scripted responses per turn."""

    def __init__(
        self,
        responses: list[list[Any]],
        fail_query_at: int | None = None,
        fail_receive_at: int | None = None,
    ) -> None:
        self.responses = list(responses)
        self.fail_query_at = fail_query_at
        self.fail_receive_at = fail_receive_at
        self.prompts: list[str] = []
        self.connects = 0
        self.disconnects = 0
        self.interrupts = 0
        self.during_receive: list[Callable[[], Awaitable[None]]] = []

    async def connect(self) -> None:
        self.connects += 1

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def query(self, prompt: str, session_id: str = "default") -> None:
        if self.fail_query_at == len(self.prompts):
            raise ConnectionError("cli died")
        self.prompts.append(prompt)

    async def receive_response(self):
        turn_index = len(self.prompts) - 1
        for hook in self.during_receive:
            await hook()
        for message in self.responses.pop(0):
            yield message
            if turn_index == self.fail_receive_at:
                raise ConnectionError("cli died mid-turn")

    async def interrupt(self) -> None:
        self.interrupts += 1


def turn_messages(text: str, session_id: str = "s1", structured: dict | None = STRUCTURED):
    return [
        AssistantMessage(content=[TextBlock(text=text)], model="m"),
        result_message(session_id=session_id, structured_output=structured, result="(resultado)"),
    ]


def spec() -> AgentSpec:
    return AgentSpec(
        name="jarvis",
        role="front",
        model="claude-haiku",
        system_prompt="Eres Jarvis.",
        path=Path("/tmp/jarvis"),
        tools=ToolConfig(native=["remember"]),
    )


def make_conversation(clients: list[FakeSessionClient]):
    captured: list[Any] = []

    def factory(options):
        captured.append(options)
        return clients.pop(0)

    async def call(qualified, args, timeout):
        raise NotImplementedError

    conversation = ClaudeSdkConversation(
        load_settings(None), AutoConfirmGate(True), call, client_factory=factory
    )
    return conversation, captured


async def test_open_connects_once_and_turns_share_the_session() -> None:
    client = FakeSessionClient([turn_messages("Hola, señor."), turn_messages("Renzo.")])
    conversation, captured = make_conversation([client])
    sink = ListEventSink()

    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), sink)
    first = await conversation.turn("me llamo Renzo")
    second = await conversation.turn("¿cómo me llamo?")

    assert client.connects == 1
    assert client.prompts == ["me llamo Renzo", "¿cómo me llamo?"]
    assert conversation.session_id == "s1"
    assert first == FrontTurn(
        text="Hola, señor.",
        structured=STRUCTURED,
        usage={"input_tokens": 100, "output_tokens": 40, "total_cost_usd": 0.0123, "num_turns": 3},
    )
    assert second.text == "Renzo."
    assert sink.payloads("assistant.text") == [{"text": "Hola, señor."}, {"text": "Renzo."}]
    assert len(captured) == 1
    assert captured[0].resume is None
    assert list(captured[0].mcp_servers) == ["tony"]


async def test_turn_without_assistant_text_uses_the_result_text() -> None:
    client = FakeSessionClient([[result_message(result="solo resultado", structured_output=None)]])
    conversation, _ = make_conversation([client])
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink())

    turn = await conversation.turn("x")

    assert turn == FrontTurn(
        text="solo resultado",
        structured=None,
        usage={"input_tokens": 100, "output_tokens": 40, "total_cost_usd": 0.0123, "num_turns": 3},
    )


async def test_interrupt_and_close_reach_the_client() -> None:
    client = FakeSessionClient([])
    conversation, _ = make_conversation([client])
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink())

    await conversation.interrupt()
    await conversation.close()

    assert client.interrupts == 1
    assert client.disconnects == 1


async def test_dead_client_is_reopened_with_resume_and_the_turn_retried() -> None:
    first = FakeSessionClient([turn_messages("uno")], fail_query_at=1)
    second = FakeSessionClient([turn_messages("dos", session_id="s1")])
    conversation, captured = make_conversation([first, second])
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink())
    await conversation.turn("a")

    turn = await conversation.turn("b")

    assert turn.text == "dos"
    assert second.prompts == ["b"]
    assert second.connects == 1
    assert first.disconnects == 1
    assert captured[1].resume == "s1"
    assert conversation.session_id == "s1"


async def test_failure_before_any_session_id_propagates() -> None:
    first = FakeSessionClient([], fail_query_at=0)
    conversation, _ = make_conversation([first])
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink())

    with pytest.raises(ConnectionError):
        await conversation.turn("a")


async def test_turn_before_open_is_an_error() -> None:
    conversation, _ = make_conversation([])

    with pytest.raises(RuntimeError, match="^la sesión del front no está abierta$"):
        await conversation.turn("a")


async def test_open_builds_proxies_for_the_front_catalog() -> None:
    client = FakeSessionClient([])
    conversation, captured = make_conversation([client])

    await conversation.open(spec(), fake_catalog(allow=["fake.echo"]), Handlers(), ListEventSink())

    options = captured[0]
    assert list(options.mcp_servers) == ["tony", "fake"]
    assert options.allowed_tools == ["mcp__tony__*", "mcp__fake__*"]
    assert options.model == "claude-haiku-5-5"


async def test_turn_that_fails_after_the_prompt_was_sent_is_never_resent() -> None:
    first = FakeSessionClient([turn_messages("uno"), turn_messages("dos")], fail_receive_at=1)
    second = FakeSessionClient([turn_messages("tres", session_id="s1")])
    conversation, captured = make_conversation([first, second])
    sink = ListEventSink()
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), sink)
    await conversation.turn("a")

    failed = await conversation.turn("b")

    assert second.prompts == []
    assert failed.structured is None
    assert failed.error == "ConnectionError: cli died mid-turn"
    assert failed.text == (
        "No pude completar el turno: se perdió la conexión con el modelo y el resultado de "
        "las acciones ya iniciadas es desconocido; no las repitas sin comprobarlo. "
        "Diagnóstico: ConnectionError: cli died mid-turn"
    )
    assert sink.payloads("turn.error") == [{"diagnostic": "ConnectionError: cli died mid-turn"}]

    recovered = await conversation.turn("c")

    assert recovered.text == "tres"
    assert second.prompts == ["c"]
    assert first.disconnects == 1
    assert captured[1].resume == "s1"


async def test_error_result_message_yields_an_explicit_failed_turn() -> None:
    client = FakeSessionClient(
        [
            [
                AssistantMessage(content=[TextBlock(text="Voy a hacerlo")], model="m"),
                result_message(is_error=True, subtype="error_max_turns", result="max turns"),
            ]
        ]
    )
    conversation, _ = make_conversation([client])
    sink = ListEventSink()
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), sink)

    turn = await conversation.turn("x")

    assert "Voy a hacerlo" not in turn.text
    assert turn.text == (
        "No pude completar el turno: el modelo terminó con un error. "
        "Diagnóstico: error_max_turns: max turns"
    )
    assert turn.structured is None
    assert turn.error == "error_max_turns: max turns"
    assert turn.usage["input_tokens"] == 100
    assert sink.payloads("turn.error") == [{"diagnostic": "error_max_turns: max turns"}]
    assert conversation.session_id == "s"


async def test_each_turn_gets_a_fresh_cancel_state_wired_to_interrupt() -> None:
    client = FakeSessionClient([turn_messages("uno"), turn_messages("dos")])
    conversation, _ = make_conversation([client])
    await conversation.open(spec(), fake_catalog(allow=["fake.echo"]), Handlers(), ListEventSink())
    seen: list[Any] = []

    async def reject_a_tool() -> None:
        state = conversation.turn_state
        seen.append(state)
        state.cancel("fake.destroy")
        await state.request_interrupt()

    client.during_receive = [reject_a_tool]
    await conversation.turn("a")
    client.during_receive = []

    await conversation.turn("b")

    assert seen[0].cancelled is True
    assert seen[0].task_id == "front"
    assert client.interrupts == 1
    assert conversation.turn_state is not seen[0]
    assert conversation.turn_state.cancelled is False


async def test_open_with_resume_passes_it_to_the_client_options() -> None:
    client = FakeSessionClient([])
    conversation, captured = make_conversation([client])

    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink(), resume="s9")

    assert captured[0].resume == "s9"
    assert client.connects == 1


@pytest.mark.parametrize(
    ("result", "errors", "expected"),
    [
        (None, ["rate limit", "retry later"], "error_during_execution: rate limit; retry later"),
        (None, None, "error_during_execution: sin detalle"),
        ("", [], "error_during_execution: sin detalle"),
    ],
)
async def test_failed_turn_diagnostic_falls_back_to_errors_then_a_placeholder(
    result, errors, expected
) -> None:
    client = FakeSessionClient(
        [
            [
                result_message(
                    is_error=True, subtype="error_during_execution", result=result, errors=errors
                )
            ]
        ]
    )
    conversation, _ = make_conversation([client])
    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink())

    turn = await conversation.turn("x")

    assert turn.error == expected


async def test_turn_accepts_a_text_callback_that_v1_never_invokes() -> None:
    client = FakeSessionClient([turn_messages("Hola, señor.")])
    conversation, _ = make_conversation([client])
    seen: list[str] = []

    async def on_text(text: str) -> None:
        seen.append(text)

    await conversation.open(spec(), ToolCatalog.empty(), Handlers(), ListEventSink())
    turn = await conversation.turn("hola", on_text=on_text)

    assert turn.text == "Hola, señor."
    assert seen == []
