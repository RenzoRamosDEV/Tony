import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, StreamEvent

from tests.core.orchestrator.test_claude_engine import (
    CONTEXT,
    FakeSdkClient,
    assistant,
    result_message,
)
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.claude_engine import BUILTIN_TOOLS, ClaudeEngine, EngineError
from tony.core.orchestrator.ports import ChatOutcome, ProxiedTool, ToolReply, Usage

SPEC = AgentSpec(
    name="jarvis",
    role="front",
    model="claude-haiku",
    persona={"language": "es", "tone": "t"},
    voice={"tts": "kokoro/em_alex"},
    system_prompt="Cuerpo",
)


def delta(text, kind="text_delta"):
    return StreamEvent(
        uuid="u",
        session_id="s",
        event={
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": kind, "text" if kind == "text_delta" else "partial_json": text},
        },
    )


async def handler(args):
    return ToolReply(text="")


TOOLS = [
    ProxiedTool("tony.delegate", "d", {}, handler),
    ProxiedTool("clima.hoy", "d", {}, handler),
]


async def converse(messages):
    clients, chunks = [], []

    def factory(options):
        clients.append(FakeSdkClient(options, messages))
        return clients[-1]

    outcome = await ClaudeEngine(client_factory=factory).converse(
        SPEC, "Sistema completo", "<mensaje>Hola</mensaje>", TOOLS, "haiku-id", chunks.append
    )
    return outcome, chunks, clients[0]


async def test_streams_text_deltas_in_order_and_returns_the_final_text():
    messages = [
        delta("Buenas"),
        StreamEvent(uuid="u", session_id="s", event={"type": "message_start"}),
        delta("{}", kind="input_json_delta"),
        delta(" tardes, señor."),
        assistant("Buenas tardes, señor."),
        result_message(result="Buenas tardes, señor.", structured_output=None),
    ]

    outcome, chunks, client = await converse(messages)

    assert chunks == ["Buenas", " tardes, señor."]
    assert outcome == ChatOutcome(text="Buenas tardes, señor.", usage=[Usage(120, 30, 5)])
    assert client.queries == ["<mensaje>Hola</mensaje>"]
    assert client.entered and client.exited


async def test_options_are_conversational():
    _, _, client = await converse([result_message(structured_output=None)])
    options = client.options

    assert options.output_format is None
    assert options.include_partial_messages is True
    assert options.system_prompt == "Sistema completo"
    assert options.model == "haiku-id"
    assert options.tools == []
    assert options.disallowed_tools == list(BUILTIN_TOOLS)
    assert sorted(options.mcp_servers) == ["clima", "tony"]


@pytest.mark.parametrize("name", ["mcp__tony__delegate", "mcp__clima__hoy"])
async def test_merged_catalog_is_allowed(name):
    _, _, client = await converse([result_message()])

    assert isinstance(await client.options.can_use_tool(name, {}, CONTEXT), PermissionResultAllow)


@pytest.mark.parametrize("name", ["Bash", "mcp__tony__remember", "mcp__filesystem__read_file"])
async def test_anything_else_is_denied(name):
    _, _, client = await converse([result_message()])

    assert isinstance(await client.options.can_use_tool(name, {}, CONTEXT), PermissionResultDeny)


async def test_error_result_raises():
    with pytest.raises(EngineError, match="error_during_execution"):
        await converse(
            [result_message(is_error=True, subtype="error_during_execution", result=None)]
        )


async def test_without_result_message_uses_the_last_assistant_text():
    outcome, _, _ = await converse([assistant("solo esto")])

    assert outcome == ChatOutcome(text="solo esto", usage=[])
