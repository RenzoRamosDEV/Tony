from collections.abc import AsyncIterator, Callable
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query

from tony.core.orchestrator.claude_engine import outcome_from_messages

Query = Callable[..., AsyncIterator[Any]]


class ClaudeWording:
    """QuestionWording adapter: one tool-less Claude Agent SDK turn with Edith's prompt."""

    def __init__(self, system_prompt: str, model_id: str, *, query: Query = query) -> None:
        self._system_prompt = system_prompt
        self._model_id = model_id
        self._query = query

    async def word(self, tool: str, preview: str, rule: str) -> str:
        options = ClaudeAgentOptions(
            tools=[],
            setting_sources=[],
            max_turns=1,
            system_prompt=self._system_prompt,
            model=self._model_id,
        )
        prompt = f"Tool: {tool}\nArgumentos: {preview}\nRegla: {rule}"
        messages = [message async for message in self._query(prompt=prompt, options=options)]
        return outcome_from_messages(messages).text
