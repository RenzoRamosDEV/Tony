from typing import Any

from pydantic import ValidationError

from tony.core.evidence.apply import SOURCES_KEY
from tony.core.evidence.source import Source

HEADER = "Fuentes:"


def source_lines(datos: Any) -> list[str]:
    """`Fuentes:` plus one `- connector · title` line per valid source; empty when none."""
    if not isinstance(datos, dict) or not isinstance(datos.get(SOURCES_KEY), list):
        return []
    lines = [
        f"- {source.connector} · {source.title}"
        for source in map(_parse, datos[SOURCES_KEY])
        if source is not None
    ]
    return [HEADER, *lines] if lines else []


def _parse(entry: Any) -> Source | None:
    try:
        return Source.model_validate(entry)
    except ValidationError:
        return None
