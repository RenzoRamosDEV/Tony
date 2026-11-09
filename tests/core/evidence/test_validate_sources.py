import pytest

from tony.core.evidence.validate import validate_sources

OBSERVED = ["Factura 123\nTotal:   45 EUR  pagada", "otro texto"]


def source(excerpt="Total: 45 EUR", title="Factura", **extra):
    return {
        "connector": "gmail",
        "id": "m1",
        "title": title,
        "retrieved_at": "2026-11-01T09:00:00Z",
        "excerpt": excerpt,
        **extra,
    }


def test_exact_excerpt_is_kept():
    check = validate_sources([source("otro texto")], OBSERVED)

    assert [item.excerpt for item in check.kept] == ["otro texto"]
    assert check.warnings == []


def test_whitespace_and_newline_differences_are_ignored():
    check = validate_sources([source("Factura 123 Total: 45 EUR pagada")], OBSERVED)

    assert len(check.kept) == 1


def test_whitespace_differences_in_excerpt_are_ignored():
    check = validate_sources([source("Total:\n 45   EUR")], OBSERVED)

    assert len(check.kept) == 1


def test_case_difference_is_dropped():
    check = validate_sources([source("total: 45 eur")], OBSERVED)

    assert check.kept == []
    assert len(check.warnings) == 1


def test_invented_excerpt_is_dropped_naming_the_title_without_the_excerpt():
    check = validate_sources([source("inventado", title="Factura")], OBSERVED)

    assert check.kept == []
    assert check.warnings == [
        "fuente descartada: «Factura» — el extracto no aparece en ningún resultado de herramienta"
    ]


@pytest.mark.parametrize("excerpt", ["", "   ", "\n\t"])
def test_empty_excerpt_is_dropped(excerpt):
    check = validate_sources([source(excerpt)], ["", "  ", "algo"])

    assert check.kept == []
    assert len(check.warnings) == 1


def test_300_characters_valid_and_301_invalid():
    text = "a" * 301

    ok = validate_sources([source("a" * 300)], [text])
    too_long = validate_sources([source("a" * 301)], [text])

    assert len(ok.kept) == 1
    assert too_long.kept == []
    assert too_long.warnings == ["fuente descartada: entrada 1 no válida"]


@pytest.mark.parametrize(
    "entry", ["texto", None, 3, ["x"], {"connector": "gmail"}, {**source(), "id": 5}]
)
def test_invalid_entry_is_dropped_with_one_based_index(entry):
    check = validate_sources([source("otro texto"), entry], OBSERVED)

    assert len(check.kept) == 1
    assert check.warnings == ["fuente descartada: entrada 2 no válida"]


def test_entry_missing_one_field_is_invalid():
    entry = source()
    del entry["retrieved_at"]

    check = validate_sources([entry], OBSERVED)

    assert check.kept == []
    assert check.warnings == ["fuente descartada: entrada 1 no válida"]


def test_title_is_cut_at_80_characters_in_the_warning():
    check = validate_sources([source("nada", title="t" * 81)], OBSERVED)

    assert check.warnings == [
        f"fuente descartada: «{'t' * 80}» — el extracto no aparece en ningún "
        "resultado de herramienta"
    ]


def test_title_of_exactly_80_characters_is_not_cut():
    check = validate_sources([source("nada", title="t" * 80)], OBSERVED)

    assert "t" * 80 + "»" in check.warnings[0]


def test_no_observed_texts_drops_everything():
    check = validate_sources([source(), source("otro texto")], [])

    assert check.kept == []
    assert len(check.warnings) == 2


def test_order_is_preserved_and_extra_fields_are_not_kept():
    check = validate_sources(
        [source("otro texto", title="B", extra="x"), source("Total: 45 EUR", title="A")], OBSERVED
    )

    assert [item.title for item in check.kept] == ["B", "A"]
    assert "extra" not in check.kept[0].model_dump()
