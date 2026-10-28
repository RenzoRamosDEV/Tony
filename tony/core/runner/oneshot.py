"""One single-turn request to a model: no tools, no settings, optional JSON schema."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from tony.core.config import TonySettings
from tony.core.runner.claude_sdk import BUILTIN_TOOLS, SdkClient, assistant_text

JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class OneShotError(Exception):
    pass


async def one_shot(
    settings: TonySettings,
    model_alias: str,
    prompt: str,
    schema: dict[str, Any] | None = None,
    client_factory: Callable[[ClaudeAgentOptions], SdkClient] = ClaudeSDKClient,
    max_turns: int = 1,
) -> str | dict[str, Any]:
    model = settings.models.get(model_alias)
    if model is None:
        raise OneShotError(f"alias de modelo desconocido '{model_alias}'")
    options = ClaudeAgentOptions(
        tools=[],
        allowed_tools=[],
        disallowed_tools=list(BUILTIN_TOOLS),
        system_prompt=None,
        permission_mode="default",
        max_turns=max_turns,
        model=model,
        setting_sources=[],
        strict_mcp_config=True,
        output_format={"type": "json_schema", "schema": schema} if schema else None,
        include_partial_messages=False,
    )
    final, text = await _ask(client_factory(options), prompt)
    if final is not None and final.is_error:
        raise OneShotError(f"{final.subtype}: {final.result or 'sin detalle'}")
    result_text = (final.result if final is not None and final.result else None) or text
    if schema is None:
        return result_text
    if final is not None and final.structured_output is not None:
        return final.structured_output
    return _first_json_object(result_text)


async def _ask(client: SdkClient, prompt: str) -> tuple[ResultMessage | None, str]:
    final: ResultMessage | None = None
    text = ""
    async with client:
        await client.query(prompt)
        async for message in client.receive_response():
            piece = assistant_text(message)
            if piece is not None:
                text = piece
            if isinstance(message, ResultMessage):
                final = message
    return final, text


def _first_json_object(text: str) -> dict[str, Any]:
    match = JSON_OBJECT.search(text)
    if match is not None:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    raise OneShotError(f"la respuesta no contiene un objeto JSON: {text[:80]!r}")
