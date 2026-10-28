"""Unit tests for split_frontmatter."""

from __future__ import annotations

import pytest

from tony.core.loader import split_frontmatter
from tony.core.loader.frontmatter import FrontmatterError


def test_splits_header_and_body_preserving_inner_newlines() -> None:
    header, body = split_frontmatter("---\nname: x\nrole: worker\n---\nLínea 1\n\nLínea 2\n")

    assert header == {"name": "x", "role": "worker"}
    assert body == "Línea 1\n\nLínea 2"


def test_empty_header_yields_empty_mapping() -> None:
    assert split_frontmatter("---\n---\ncuerpo") == ({}, "cuerpo")


@pytest.mark.parametrize("text", ["", "sin delimitador\n", "texto\n---\nname: x\n---\n"])
def test_missing_opening_delimiter(text: str) -> None:
    with pytest.raises(FrontmatterError, match="falta el frontmatter"):
        split_frontmatter(text)


def test_missing_closing_delimiter() -> None:
    with pytest.raises(FrontmatterError, match="de cierre"):
        split_frontmatter("---\nname: x\n")


def test_non_mapping_header_is_rejected() -> None:
    with pytest.raises(FrontmatterError, match="mapa YAML"):
        split_frontmatter("---\n- a\n- b\n---\ncuerpo")


def test_invalid_yaml_header_is_rejected() -> None:
    with pytest.raises(FrontmatterError, match="YAML"):
        split_frontmatter("---\nname: [\n---\ncuerpo")
