"""Atomic edits preserve the markdown body and reject invalid headers."""

import pytest

from tony.core.loader.frontmatter import FrontmatterError


@pytest.mark.parametrize("body", ["\n  Instrucción.  \n\n", "\r\nTexto\r\n", "sin salto final"])
def test_edit_preserves_body_and_other_fields(tmp_path, body):
    from tony.core.loader.agentmd import edit_agent_frontmatter

    path = tmp_path / "agent.md"
    path.write_bytes(("---\nname: viernes\nrole: worker\n---\n" + body).encode())
    result = edit_agent_frontmatter(path, lambda data: {**data, "engine": "openai_gpt"})
    assert result == {"name": "viernes", "role": "worker", "engine": "openai_gpt"}
    assert (
        path.read_bytes()
        == ("---\nname: viernes\nrole: worker\nengine: openai_gpt\n---\n" + body).encode()
    )


@pytest.mark.parametrize(
    "text",
    ["No header", "---\nname: x", "---\n[broken\n---\n", "---\n- x\n---\n", "---\nfalse\n---\n"],
)
def test_invalid_header_leaves_file_untouched(tmp_path, text):
    from tony.core.loader.agentmd import edit_agent_frontmatter

    path = tmp_path / "agent.md"
    path.write_text(text)
    with pytest.raises(FrontmatterError):
        edit_agent_frontmatter(path, lambda data: {**data, "engine": "openai_gpt"})
    assert path.read_text() == text


def test_failed_replacement_leaves_original(tmp_path, monkeypatch):
    from tony.core.config import atomic
    from tony.core.loader.agentmd import edit_agent_frontmatter

    path = tmp_path / "agent.md"
    original = "---\nname: viernes\n---\nBody\n"
    path.write_text(original)

    def fail(*args):
        raise OSError("replacement failed")

    monkeypatch.setattr(atomic.os, "replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        edit_agent_frontmatter(path, lambda data: {**data, "engine": "openai_gpt"})
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]


def test_edit_replaces_profile_and_callback_failure_does_not_write(tmp_path):
    from tony.core.loader.agentmd import edit_agent_frontmatter

    path = tmp_path / "agent.md"
    path.write_text("---\nengine: old\nname: viernes\n---\nBody\n")

    def fail(header):
        header["engine"] = "partial"
        raise ValueError("edit failed")

    before = path.read_bytes()
    with pytest.raises(ValueError, match="edit failed"):
        edit_agent_frontmatter(path, fail)
    assert path.read_bytes() == before
    edit_agent_frontmatter(path, lambda header: {**header, "engine": "new"})
    assert path.read_text() == "---\nengine: new\nname: viernes\n---\nBody\n"
