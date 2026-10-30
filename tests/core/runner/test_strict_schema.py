"""`strict_schema`: makes a Pydantic JSON Schema valid for OpenAI/Codex structured output.

Codex's `--output-schema` goes through an OpenAI-style strict `response_format`, which
rejects a schema where `required` does not list every key in `properties` (discovered
against the real `codex` binary: `Invalid schema for response_format ...: 'schema.required'
is required to include every key in properties`). Pydantic only lists fields without a
default as required, so every model with an optional field needs this adjustment before
it reaches `--output-schema`.
"""

from __future__ import annotations

from tony.core.runner.contracts import TaskResult
from tony.core.runner.reply_mode import FrontReply
from tony.core.runner.strict_schema import strict_schema


def test_every_property_of_task_result_becomes_required() -> None:
    schema = strict_schema(TaskResult)

    assert set(schema["required"]) == set(schema["properties"])


def test_every_property_of_front_reply_becomes_required() -> None:
    schema = strict_schema(FrontReply)

    assert set(schema["required"]) == set(schema["properties"])
