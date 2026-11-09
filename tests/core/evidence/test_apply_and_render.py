import pytest

from tony.core.events.messages import TaskResult
from tony.core.evidence.apply import apply_evidence
from tony.core.evidence.observed import ObservedTexts
from tony.core.evidence.render import source_lines

OBSERVED = ["Total: 45 EUR"]
REAL = {
    "connector": "gmail",
    "id": "m1",
    "title": "Factura",
    "retrieved_at": "2026-11-01T09:00:00Z",
    "excerpt": "Total: 45 EUR",
}
FAKE = {**REAL, "title": "Inventada", "excerpt": "no existe"}


@pytest.mark.parametrize("datos", [None, [1, 2], "texto", 5, {"otro": 1}])
def test_result_without_fuentes_is_unchanged(datos):
    result = TaskResult(resumen="r", datos=datos, pasos=["p"], errores=["e"])

    assert apply_evidence(result, OBSERVED) == result


def test_fuentes_is_replaced_by_the_kept_sources_and_warnings_go_to_pasos():
    result = TaskResult(
        resumen="r", datos={"x": 1, "fuentes": [REAL, FAKE]}, pasos=["leí"], errores=[]
    )

    applied = apply_evidence(result, OBSERVED)

    assert applied.datos == {"x": 1, "fuentes": [REAL]}
    assert applied.pasos == [
        "leí",
        "fuente descartada: «Inventada» — el extracto no aparece en ningún "
        "resultado de herramienta",
    ]
    assert applied.errores == []
    assert applied.resumen == "r"


def test_errores_are_untouched():
    result = TaskResult(resumen="r", datos={"fuentes": [FAKE]}, errores=["fallo"])

    assert apply_evidence(result, OBSERVED).errores == ["fallo"]


def test_non_list_fuentes_is_removed_with_a_warning():
    result = TaskResult(resumen="r", datos={"x": 1, "fuentes": "mal"})

    applied = apply_evidence(result, OBSERVED)

    assert applied.datos == {"x": 1}
    assert applied.pasos == ["fuentes ignoradas: no es una lista"]


def test_input_is_not_mutated():
    result = TaskResult(resumen="r", datos={"fuentes": [REAL, FAKE]}, pasos=["a"])
    before = result.model_dump()

    apply_evidence(result, OBSERVED)

    assert result.model_dump() == before


def test_all_sources_dropped_leaves_an_empty_list():
    result = TaskResult(resumen="r", datos={"fuentes": [FAKE]})

    assert apply_evidence(result, []).datos == {"fuentes": []}


def test_observed_texts_is_append_only_and_ordered():
    observed = ObservedTexts()
    assert observed.texts() == ()

    observed.add("a")
    snapshot = observed.texts()
    observed.add("b")

    assert snapshot == ("a",)
    assert observed.texts() == ("a", "b")


@pytest.mark.parametrize("datos", [None, "x", [1], {}, {"fuentes": []}, {"fuentes": "x"}])
def test_source_lines_empty_when_nothing_to_show(datos):
    assert source_lines(datos) == []


def test_source_lines_lists_connector_and_title_skipping_invalid_entries():
    datos = {
        "fuentes": [
            REAL,
            "basura",
            {"connector": "x"},
            {**REAL, "connector": "gdrive", "title": "Acta"},
        ]
    }

    assert source_lines(datos) == ["Fuentes:", "- gmail · Factura", "- gdrive · Acta"]


def test_source_lines_empty_when_all_entries_invalid():
    assert source_lines({"fuentes": ["basura"]}) == []
