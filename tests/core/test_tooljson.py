"""Pure edits of tool.json and its atomic write (specs/cli-mcp)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tony.core.config import atomic
from tony.core.loader.tooljson import (
    ToolJsonError,
    read_tool_json,
    remove_server,
    upsert_server,
    write_tool_json,
)

EXISTING = {
    "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "fs"]}},
    "native": ["read_skill"],
    "allow": ["filesystem.*"],
    "confirm": ["filesystem.write_file"],
    "x-custom": {"keep": True},
}
FETCH = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"]}


def test_read_returns_empty_dict_without_file(tmp_path: Path) -> None:
    assert read_tool_json(tmp_path / "tool.json") == {}


def test_read_rejects_invalid_json_and_non_objects(tmp_path: Path) -> None:
    path = tmp_path / "tool.json"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ToolJsonError, match="tool.json"):
        read_tool_json(path)

    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ToolJsonError, match="objeto"):
        read_tool_json(path)


def test_read_parses_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "tool.json"
    path.write_text(json.dumps(EXISTING), encoding="utf-8")

    assert read_tool_json(path) == EXISTING


def test_upsert_adds_the_server_and_preserves_everything_else() -> None:
    data = upsert_server(json.loads(json.dumps(EXISTING)), "fetch", FETCH)

    assert data["mcpServers"] == {
        "filesystem": EXISTING["mcpServers"]["filesystem"],
        "fetch": FETCH,
    }
    assert data["native"] == ["read_skill"]
    assert data["allow"] == ["filesystem.*"]
    assert data["confirm"] == ["filesystem.write_file"]
    assert data["x-custom"] == {"keep": True}
    assert list(data) == ["mcpServers", "native", "allow", "confirm", "x-custom"]


def test_upsert_creates_mcp_servers_in_an_empty_file() -> None:
    assert upsert_server({}, "fetch", FETCH) == {"mcpServers": {"fetch": FETCH}}


def test_upsert_appends_allow_and_confirm_without_duplicates() -> None:
    data = upsert_server(
        json.loads(json.dumps(EXISTING)),
        "notion",
        {"url": "https://n"},
        allow=["notion.search", "filesystem.*"],
        confirm=["notion.delete", "filesystem.write_file"],
    )

    assert data["allow"] == ["filesystem.*", "notion.search"]
    assert data["confirm"] == ["filesystem.write_file", "notion.delete"]


def test_upsert_rejects_an_existing_name_unless_forced() -> None:
    data = upsert_server({}, "fetch", {"command": "a"})

    with pytest.raises(ToolJsonError) as info:
        upsert_server(data, "fetch", {"command": "b"})
    assert "fetch" in str(info.value) and "--force" in str(info.value)
    assert data["mcpServers"]["fetch"] == {"command": "a"}

    forced = upsert_server(data, "fetch", {"command": "b"}, force=True)
    assert forced["mcpServers"]["fetch"] == {"command": "b"}


def test_remove_deletes_only_the_server() -> None:
    data = remove_server(json.loads(json.dumps(EXISTING)), "filesystem")

    assert data["mcpServers"] == {}
    assert data["allow"] == ["filesystem.*"] and data["confirm"] == ["filesystem.write_file"]
    assert data["native"] == ["read_skill"]


def test_remove_of_an_unknown_server_fails_naming_it() -> None:
    with pytest.raises(ToolJsonError, match="nadie"):
        remove_server(json.loads(json.dumps(EXISTING)), "nadie")
    with pytest.raises(ToolJsonError, match="nadie"):
        remove_server({}, "nadie")


def test_write_uses_two_space_indent_and_keeps_unicode(tmp_path: Path) -> None:
    path = tmp_path / "tool" / "tool.json"

    write_tool_json(path, {"mcpServers": {"ñ": {"command": "a"}}})

    text = path.read_text(encoding="utf-8")
    assert text == '{\n  "mcpServers": {\n    "ñ": {\n      "command": "a"\n    }\n  }\n}\n'
    assert read_tool_json(path) == {"mcpServers": {"ñ": {"command": "a"}}}


def test_failed_replace_leaves_the_original_and_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "tool.json"
    path.write_text("{}", encoding="utf-8")

    def failing_replace(src, dst):
        raise OSError("disco lleno")

    monkeypatch.setattr(atomic.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disco lleno"):
        write_tool_json(path, {"mcpServers": {}})

    assert path.read_text(encoding="utf-8") == "{}"
    assert [p.name for p in tmp_path.iterdir()] == ["tool.json"]


def test_error_messages_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "tool.json"
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ToolJsonError) as not_object:
        read_tool_json(path)
    assert str(not_object.value) == "tool.json: debe ser un objeto JSON"

    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ToolJsonError) as invalid:
        read_tool_json(path)
    assert str(invalid.value).startswith("tool.json inválido: Expecting")

    with pytest.raises(ToolJsonError) as existing:
        upsert_server({"mcpServers": {"fetch": {}}}, "fetch", {})
    assert str(existing.value) == "el servidor 'fetch' ya existe; usa --force para sustituirlo"

    with pytest.raises(ToolJsonError) as missing:
        remove_server({"mcpServers": {}}, "nadie")
    assert str(missing.value) == "el servidor 'nadie' no existe en mcpServers"
