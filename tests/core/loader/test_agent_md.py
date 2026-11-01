import pytest

from tony.core.config.errors import DefinitionError
from tony.core.loader.agent_md import split_frontmatter

FILE = "agents/viernes/agent.md"


def test_splits_frontmatter_and_body():
    text = "---\nname: viernes\nrole: worker\n---\n\nEres Viernes.\n\nSegunda linea.\n"

    frontmatter, body = split_frontmatter(text, FILE)

    assert frontmatter == {"name": "viernes", "role": "worker"}
    assert body == "Eres Viernes.\n\nSegunda linea."


def test_body_may_contain_delimiter_lines():
    frontmatter, body = split_frontmatter("---\na: 1\n---\nuno\n---\ndos\n", FILE)

    assert (frontmatter, body) == ({"a": 1}, "uno\n---\ndos")


def test_accepts_crlf_line_endings():
    frontmatter, body = split_frontmatter("---\r\na: 1\r\n---\r\ncuerpo\r\n", FILE)

    assert (frontmatter, body) == ({"a": 1}, "cuerpo")


@pytest.mark.parametrize(
    "text",
    [
        "Eres Viernes.\n",
        "\n---\na: 1\n---\ncuerpo\n",
        "--- \na: 1\n---\ncuerpo\n",
        "----\na: 1\n----\ncuerpo\n",
        "---\na: 1\ncuerpo sin cierre\n",
        "",
    ],
)
def test_missing_frontmatter_names_file(text):
    with pytest.raises(DefinitionError, match="frontmatter") as info:
        split_frontmatter(text, FILE)

    assert info.value.file == FILE


@pytest.mark.parametrize("body", ["", "\n", "   \n\t\n"])
def test_empty_body_names_file(body):
    with pytest.raises(DefinitionError, match="body") as info:
        split_frontmatter(f"---\na: 1\n---\n{body}", FILE)

    assert info.value.file == FILE


@pytest.mark.parametrize(
    ("yaml_text", "reason"),
    [("a: [unclosed", "YAML"), ("- a\n- b", "mapping"), ("just text", "mapping"), ("", "mapping")],
)
def test_invalid_yaml_names_file(yaml_text, reason):
    with pytest.raises(DefinitionError, match=reason) as info:
        split_frontmatter(f"---\n{yaml_text}\n---\ncuerpo\n", FILE)

    assert info.value.file == FILE
