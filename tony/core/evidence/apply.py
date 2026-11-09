from collections.abc import Iterable

from tony.core.events.messages import TaskResult
from tony.core.evidence.validate import validate_sources

SOURCES_KEY = "fuentes"
NOT_A_LIST_WARNING = "fuentes ignoradas: no es una lista"


def apply_evidence(result: TaskResult, observed_texts: Iterable[str]) -> TaskResult:
    """The result with `datos.fuentes` reduced to the sources the tools really returned."""
    datos = result.datos
    if not isinstance(datos, dict) or SOURCES_KEY not in datos:
        return result
    sources = datos[SOURCES_KEY]
    if not isinstance(sources, list):
        rest = {key: value for key, value in datos.items() if key != SOURCES_KEY}
        return result.model_copy(
            update={"datos": rest, "pasos": [*result.pasos, NOT_A_LIST_WARNING]}
        )
    check = validate_sources(sources, observed_texts)
    kept = [source.model_dump() for source in check.kept]
    return result.model_copy(
        update={
            "datos": {**datos, SOURCES_KEY: kept},
            "pasos": [*result.pasos, *check.warnings],
        }
    )
