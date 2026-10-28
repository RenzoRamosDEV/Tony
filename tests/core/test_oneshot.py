"""one_shot: the minimal single-turn request used by doctor and the evals judge."""

from __future__ import annotations

import pytest

from tests.core.runner_helpers import FakeClient, result_message
from tony.core.config import load_settings
from tony.core.runner.claude_sdk import BUILTIN_TOOLS
from tony.core.runner.oneshot import OneShotError, one_shot

SETTINGS = load_settings(None)
SCHEMA = {"type": "object", "properties": {"pass": {"type": "boolean"}}}


def factory_for(client: FakeClient):
    captured = {}

    def factory(options):
        captured["options"] = options
        return client

    return factory, captured


async def test_options_are_a_single_turn_without_tools() -> None:
    factory, captured = factory_for(FakeClient([result_message(result="OK")]))

    reply = await one_shot(SETTINGS, "claude-haiku", "Responde OK", client_factory=factory)

    options = captured["options"]
    assert reply == "OK"
    assert options.max_turns == 1 and options.tools == [] and options.allowed_tools == []
    assert set(BUILTIN_TOOLS) <= set(options.disallowed_tools)
    assert options.setting_sources == [] and options.model == "claude-haiku-5-5"
    assert options.output_format is None


async def test_schema_requests_structured_output_and_returns_it() -> None:
    client = FakeClient([result_message(structured_output={"pass": True})])
    factory, captured = factory_for(client)

    reply = await one_shot(SETTINGS, "claude-haiku", "juzga", schema=SCHEMA, client_factory=factory)

    assert reply == {"pass": True}
    assert captured["options"].output_format == {"type": "json_schema", "schema": SCHEMA}
    assert client.prompts == ["juzga"]


async def test_schema_falls_back_to_the_first_json_object_in_the_text() -> None:
    message = result_message(structured_output=None, result='Veredicto: {"pass": false} fin')
    factory, _ = factory_for(FakeClient([message]))

    reply = await one_shot(SETTINGS, "claude-haiku", "juzga", schema=SCHEMA, client_factory=factory)

    assert reply == {"pass": False}


async def test_schema_without_any_json_raises() -> None:
    factory, _ = factory_for(FakeClient([result_message(structured_output=None, result="nada")]))

    with pytest.raises(OneShotError, match="JSON"):
        await one_shot(SETTINGS, "claude-haiku", "juzga", schema=SCHEMA, client_factory=factory)


async def test_error_result_raises_with_the_diagnostic() -> None:
    message = result_message(
        is_error=True, subtype="error_during_execution", result="Not logged in"
    )
    factory, _ = factory_for(FakeClient([message]))

    with pytest.raises(OneShotError, match="Not logged in"):
        await one_shot(SETTINGS, "claude-haiku", "x", client_factory=factory)


async def test_unknown_model_alias_raises() -> None:
    with pytest.raises(OneShotError, match="nadie"):
        await one_shot(SETTINGS, "nadie", "x", client_factory=factory_for(FakeClient())[0])
