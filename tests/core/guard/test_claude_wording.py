from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from tests.fakes.confirm import FakeWording
from tony.core.config.settings import TonyConfig
from tony.core.guard.claude_wording import ClaudeWording
from tony.core.guard.wording import QuestionWording, worded_question
from tony.core.loader.agent import load_agent

REPO = Path(__file__).resolve().parents[3]
QUESTION = "Acción: borrar el archivo /n/viejo.md. Regla: filesystem.delete*/confirm. ¿Autoriza?"


def result_message(result):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
        result=result,
    )


class FakeQuery:
    def __init__(self, *messages):
        self.messages = messages
        self.calls = []

    async def __call__(self, *, prompt, options):
        self.calls.append((prompt, options))
        for message in self.messages:
            yield message


async def test_one_shot_query_without_tools_or_settings():
    query = FakeQuery(AssistantMessage(content=[TextBlock(text=QUESTION)], model="m"))
    wording = ClaudeWording("Eres Edith.", "claude-haiku-5-5", query=query)

    text = await wording.word("filesystem.delete_file", '{"path": "/n/viejo.md"}', "r/confirm")

    assert text == QUESTION
    [(prompt, options)] = query.calls
    assert (options.tools, options.setting_sources, options.max_turns) == ([], [], 1)
    assert (options.system_prompt, options.model) == ("Eres Edith.", "claude-haiku-5-5")
    assert "filesystem.delete_file" in prompt
    assert '{"path": "/n/viejo.md"}' in prompt
    assert "r/confirm" in prompt


async def test_result_text_preferred_over_assistant_text():
    query = FakeQuery(
        AssistantMessage(content=[TextBlock(text="borrador")], model="m"), result_message(QUESTION)
    )

    assert await ClaudeWording("p", "m", query=query).word("t", "{}", "r") == QUESTION


def test_satisfies_wording_port():
    assert isinstance(ClaudeWording("p", "m"), QuestionWording)


@pytest.mark.evals
@pytest.mark.timeout(60)
async def test_real_model_words_question_in_template():
    config = TonyConfig()
    edith = load_agent(REPO, "edith", config, native_tools=set())
    wording = ClaudeWording(edith.spec.system_prompt, config.resolve_model(edith.spec.model))
    rule = "filesystem.delete*/confirm"
    preview = '{"path": "/home/renzo/notas/viejo.md"}'

    raw = await wording.word("filesystem.delete_file", preview, rule)
    asked = await worded_question(FakeWording(text=raw), "filesystem.delete_file", preview, rule)

    assert asked == raw.strip(), f"model text off-template: {raw!r}"
