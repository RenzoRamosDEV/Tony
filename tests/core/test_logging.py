"""Tests for the JSONL task log (specs/task-logging)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from tony.core.logging import JsonlEventSink, new_task_id

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_tool_call_event_matches_the_contract(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "01JBTASK", secrets=[])
    sink.emit("task.started", {})
    sink.emit("assistant.text", {"text": "voy"})
    sink.emit("tool.call", {"tool": "notion.search", "args": {"query": "PRs"}})
    sink.close()

    event = read_lines(sink.path)[2]
    assert list(event) == ["schema_version", "ts", "task_id", "seq", "type", "payload"]
    assert event["schema_version"] == 1
    assert TS_PATTERN.match(event["ts"])
    assert event["task_id"] == "01JBTASK"
    assert event["seq"] == 3
    assert event["type"] == "tool.call"
    assert event["payload"] == {"tool": "notion.search", "args": {"query": "PRs"}}


def test_seq_grows_from_one(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    for event_type in ("task.started", "tool.call", "tool.result", "task.finished"):
        sink.emit(event_type, {})
    sink.close()

    assert [e["seq"] for e in read_lines(sink.path)] == [1, 2, 3, 4]


def test_file_path_uses_utc_date_and_task_id(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "abc", secrets=[])
    sink.emit("task.started", {})

    today = datetime.now(UTC).strftime("%Y%m%d")
    assert sink.path == tmp_repo / "logs" / today / "abc.jsonl"
    assert sink.path.exists()
    assert len(read_lines(sink.path)) == 1
    sink.close()


def test_each_event_is_durable_without_close(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    sink.emit("task.started", {})
    sink.emit("tool.call", {"tool": "x"})

    lines = sink.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)
    sink.close()


def test_authorization_header_is_redacted(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    sink.emit("tool.call", {"headers": {"Authorization": "Bearer abc"}})
    sink.close()

    raw = sink.path.read_text(encoding="utf-8")
    assert '"Authorization": "***"' in raw
    assert "abc" not in raw


def test_dotenv_value_inside_string_is_redacted(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=["s3cr3t-value"])
    sink.emit("tool.call", {"args": {"query": "token s3cr3t-value"}})
    sink.close()

    raw = sink.path.read_text(encoding="utf-8")
    assert "token ***" in raw
    assert "s3cr3t-value" not in raw


def test_nested_api_key_is_redacted(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    sink.emit("tool.call", {"args": {"options": {"API_KEY": "xyz"}}})
    sink.close()

    assert read_lines(sink.path)[0]["payload"]["args"]["options"]["API_KEY"] == "***"


def test_close_is_idempotent_and_emit_after_close_is_ignored(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    sink.emit("task.started", {})
    sink.close()
    sink.close()

    assert len(read_lines(sink.path)) == 1


def test_new_task_id_is_32_hex_and_unique() -> None:
    first, second = new_task_id(), new_task_id()

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_unicode_is_written_unescaped(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    sink.emit("assistant.text", {"text": "añ ¿sí?"})
    sink.close()

    assert "añ ¿sí?" in sink.path.read_text(encoding="utf-8")


def test_emit_after_close_writes_nothing(tmp_repo: Path) -> None:
    sink = JsonlEventSink(tmp_repo / "logs", "t", secrets=[])
    sink.emit("task.started", {})
    sink.close()
    sink.emit("task.finished", {})

    assert len(read_lines(sink.path)) == 1


def test_nested_logs_dir_is_created_and_shared_between_tasks(tmp_path: Path) -> None:
    logs_dir = tmp_path / "deep" / "logs"
    first = JsonlEventSink(logs_dir, "a", secrets=[])
    second = JsonlEventSink(logs_dir, "b", secrets=[])
    first.emit("task.started", {})
    second.emit("task.started", {})
    first.close()
    second.close()

    assert first.path.parent == second.path.parent
    assert sorted(p.name for p in first.path.parent.iterdir()) == ["a.jsonl", "b.jsonl"]


def test_subtask_lines_carry_parent_id_and_root_lines_omit_it(tmp_repo: Path) -> None:
    child = JsonlEventSink(tmp_repo / "logs", "s1", secrets=[], parent_id="t1")
    root = JsonlEventSink(tmp_repo / "logs", "t1", secrets=[])
    child.emit("task.started", {})
    child.emit("tool.call", {"tool": "x"})
    root.emit("task.started", {})
    child.close()
    root.close()

    child_lines = read_lines(child.path)
    assert [line["parent_id"] for line in child_lines] == ["t1", "t1"]
    assert list(child_lines[0]) == [
        "schema_version",
        "ts",
        "task_id",
        "parent_id",
        "seq",
        "type",
        "payload",
    ]
    assert "parent_id" not in read_lines(root.path)[0]
