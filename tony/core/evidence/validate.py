from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from tony.core.evidence.source import Source

TITLE_MAX_CHARS = 80


@dataclass(frozen=True)
class SourceCheck:
    kept: list[Source]
    warnings: list[str]


def validate_sources(sources: Sequence[Any], observed_texts: Iterable[str]) -> SourceCheck:
    """Keep the sources whose excerpt literally appears in a text a tool returned."""
    observed = [_normalise(text) for text in observed_texts]
    kept: list[Source] = []
    warnings: list[str] = []
    for number, entry in enumerate(sources, start=1):
        try:
            source = Source.model_validate(entry)
        except ValidationError:
            warnings.append(f"fuente descartada: entrada {number} no válida")
            continue
        if _is_supported(source.excerpt, observed):
            kept.append(source)
        else:
            title = source.title[:TITLE_MAX_CHARS]
            warnings.append(
                f"fuente descartada: «{title}» — el extracto no aparece en ningún "
                "resultado de herramienta"
            )
    return SourceCheck(kept, warnings)


def _is_supported(excerpt: str, observed: list[str]) -> bool:
    needle = _normalise(excerpt)
    return bool(needle) and any(needle in text for text in observed)


def _normalise(text: str) -> str:
    return " ".join(text.split())
