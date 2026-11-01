import json

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
)

from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.claude_engine import (
    ClaudeEngine,
    EngineError,
    make_can_use_tool,
    outcome_from_messages,
)
from tony.core.orchestrator.ports import EngineOutcome, ProxiedTool, ToolReply, Usage
from tony.core.orchestrator.results import UNSTRUCTURED, to_task_result

CONTEXT = ToolPermissionContext()
STRUCTURED = {"resumen": "hecho", "datos": ["a.md"], "pasos": ["listar"], "errores": []}


def result_message(**overrides):
    fields = {
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 2,
        "session_id": "s",
        "result": "texto final",
        "structured_output": STRUCTURED,
        "usage": {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 5},
    }
    fields.update(overrides)
    return ResultMessage(**fields)


def assistant(text):
    return AssistantMessage(content=[TextBlock(text=text)], model="m")


class TestCanUseTool:
    @pytest.fixture
    def can_use_tool(self):
        return make_can_use_tool({"filesystem.read_file", "tony.now"})

    @pytest.mark.parametrize("name", ["mcp__filesystem__read_file", "mcp__tony__now"])
    async def test_catalog_name_allowed(self, can_use_tool, name):
        assert isinstance(await can_use_tool(name, {}, CONTEXT), PermissionResultAllow)

    @pytest.mark.parametrize(
        "name",
        [
            "Bash",
            "Read",
            "mcp__filesystem",
            "mcp__filesystem__",
            "mcp__filesystem__write_file",
            "mcp__github__read_file",
        ],
    )
    async def test_everything_else_denied(self, can_use_tool, name):
        decision = await can_use_tool(name, {}, CONTEXT)

        assert isinstance(decision, PermissionResultDeny)
        assert name in decision.message


class TestOutcomeFromMessages:
    def test_structured_output_and_usage(self):
        outcome = outcome_from_messages([assistant("pensando"), result_message()])

        assert outcome == EngineOutcome(
            text="texto final", structured=STRUCTURED, usage=[Usage(120, 30)]
        )

    def test_falls_back_to_last_assistant_text(self):
        messages = [assistant("uno"), assistant("dos"), result_message(result=None)]

        assert outcome_from_messages(messages).text == "dos"

    def test_missing_result_message(self):
        outcome = outcome_from_messages([assistant("solo texto")])

        assert outcome == EngineOutcome(text="solo texto", structured=None, usage=[])

    def test_missing_usage_counts_zero(self):
        outcome = outcome_from_messages([result_message(usage=None)])

        assert outcome.usage == [Usage(0, 0)]

    def test_error_result_raises_with_diagnostic(self):
        message = result_message(is_error=True, subtype="error_max_turns", result="too long")

        with pytest.raises(EngineError, match="error_max_turns: too long"):
            outcome_from_messages([message])

    def test_error_result_without_text(self):
        with pytest.raises(EngineError, match="^error_during_execution$"):
            outcome_from_messages(
                [result_message(is_error=True, subtype="error_during_execution", result=None)]
            )


class TestToTaskResult:
    def test_valid_structured_output(self):
        outcome = EngineOutcome(text="raw", structured=STRUCTURED)

        assert to_task_result(outcome) == TaskResult(**STRUCTURED)

    @pytest.mark.parametrize("structured", [None, {"datos": 1}, "texto", [1], {"resumen": 3}])
    def test_invalid_or_missing_structure(self, structured):
        result = to_task_result(EngineOutcome(text="respuesta libre", structured=structured))

        assert result == TaskResult(resumen="respuesta libre", errores=[UNSTRUCTURED])
        assert UNSTRUCTURED == "respuesta no estructurada"


class FakeSdkClient:
    def __init__(self, options, messages):
        self.options = options
        self.messages = messages
        self.queries = []
        self.entered = self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc_info):
        self.exited = True

    async def query(self, prompt):
        self.queries.append(prompt)

    async def receive_response(self):
        for message in self.messages:
            yield message


async def test_engine_run_sends_task_and_returns_outcome():
    clients = []

    def factory(options):
        clients.append(FakeSdkClient(options, [assistant("x"), result_message()]))
        return clients[0]

    async def handler(args):
        return ToolReply(text="")

    spec = AgentSpec(
        name="viernes",
        role="worker",
        model="claude-sonnet",
        persona={"language": "es", "tone": "t"},
        voice={"tts": "kokoro/x"},
        system_prompt="P",
    )
    request = TaskRequest(objetivo="Lista mis notas")
    tools = [ProxiedTool("fs.list", "d", {}, handler)]

    outcome = await ClaudeEngine(client_factory=factory).run(spec, request, tools, "model-id")

    [client] = clients
    assert outcome.structured == STRUCTURED
    assert [json.loads(query) for query in client.queries] == [request.model_dump()]
    assert client.entered and client.exited
    assert client.options.model == "model-id"
    allowed = await client.options.can_use_tool("mcp__fs__list", {}, CONTEXT)
    denied = await client.options.can_use_tool("mcp__fs__other", {}, CONTEXT)
    assert isinstance(allowed, PermissionResultAllow)
    assert isinstance(denied, PermissionResultDeny)
