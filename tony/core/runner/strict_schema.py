"""Adapts a Pydantic JSON Schema to OpenAI/Codex's strict `response_format` rules.

Discovered empirically against the real `codex` binary (see design.md "Hallazgo
empírico"): `codex exec --output-schema` rejects a schema whose `required` list does
not name every key in `properties`, with `Invalid schema for response_format
'codex_output_schema': 'schema.required' is required to include every key in
properties`. Pydantic only requires fields without a default, so every model with an
optional field (`TaskResult`, `FrontReply`) needs this adjustment before it is written
to the `--output-schema` file.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    _normalize(schema)
    return schema


def _normalize(node: Any) -> None:
    """Recursively make every object node strict: `properties`, full `required`.

    OpenAI/Codex's strict `response_format` (discovered empirically, see
    design.md "Hallazgo empírico") rejects any object-typed node, at any depth,
    that is missing `properties` or whose `required` does not list every
    property - pydantic only emits either for nodes with a fixed shape, so a
    dynamic field (e.g. `dict[str, Any]`) needs this patched in by hand.
    """
    if isinstance(node, dict):
        if node.get("type") == "object":
            node.setdefault("properties", {})
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        for value in node.values():
            _normalize(value)
    elif isinstance(node, list):
        for item in node:
            _normalize(item)
