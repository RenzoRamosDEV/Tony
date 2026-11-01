import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from tony.core.config.placeholders import SecretMasker
from tony.core.logging.task_log import JsonlTaskLog, new_task_id

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "task_log.jsonl"
TASK_ID = "0123456789abcdef0123456789abcdef"
FIXED = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


def fixed_clock():
    return FIXED


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_task_id_is_32_lowercase_hex():
    assert re.fullmatch(r"[0-9a-f]{32}", new_task_id())


def test_task_ids_are_unique():
    assert len({new_task_id() for _ in range(100)}) == 100


def test_creates_log_folder_and_file_named_after_task(tmp_path):
    log = JsonlTaskLog(tmp_path, TASK_ID, clock=fixed_clock)

    log.emit({"type": "task_started"})

    assert log.path == tmp_path / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    assert log.path.is_file()


def test_appends_one_json_object_per_line_matching_golden(tmp_path):
    log = JsonlTaskLog(tmp_path, TASK_ID, masker=SecretMasker({"s3cr3t"}), clock=fixed_clock)

    log.emit({"type": "task_started", "agent": "viernes"})
    log.emit(
        {"type": "tool_result", "content": "token=s3cr3t ok", "nested": {"list": ["s3cr3t", 1]}}
    )

    assert log.path.read_text() == GOLDEN.read_text()


def test_appends_to_existing_file(tmp_path):
    JsonlTaskLog(tmp_path, TASK_ID, clock=fixed_clock).emit({"type": "a"})
    JsonlTaskLog(tmp_path, TASK_ID, clock=fixed_clock).emit({"type": "b"})

    path = tmp_path / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    assert [line["type"] for line in read_lines(path)] == ["a", "b"]


def test_timestamp_is_converted_to_utc(tmp_path):
    local = datetime(2026, 11, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    log = JsonlTaskLog(tmp_path, TASK_ID, clock=lambda: local)

    log.emit({"type": "x"})

    assert read_lines(log.path)[0]["ts"] == "2026-11-01T10:00:00+00:00"


def test_default_clock_writes_current_utc_time(tmp_path):
    log = JsonlTaskLog(tmp_path, TASK_ID)
    before = datetime.now(UTC)

    log.emit({"type": "x"})

    written = datetime.fromisoformat(read_lines(log.path)[0]["ts"])
    assert written.utcoffset() == timedelta(0)
    assert before <= written <= datetime.now(UTC)


def test_envelope_fields_cannot_be_overridden_by_event(tmp_path):
    log = JsonlTaskLog(tmp_path, TASK_ID, clock=fixed_clock)

    log.emit({"type": "x", "task_id": "other", "ts": "yesterday"})

    line = read_lines(log.path)[0]
    assert (line["task_id"], line["ts"]) == (TASK_ID, "2026-11-01T10:00:00+00:00")


def test_secrets_registered_later_are_masked(tmp_path):
    masker = SecretMasker()
    log = JsonlTaskLog(tmp_path, TASK_ID, masker=masker, clock=fixed_clock)

    masker.register({"late"})
    log.emit({"type": "x", "v": "late"})

    assert read_lines(log.path)[0]["v"] == "***"


def test_non_ascii_text_is_kept_readable(tmp_path):
    log = JsonlTaskLog(tmp_path, TASK_ID, clock=fixed_clock)

    log.emit({"type": "x", "v": "canción"})

    assert "canción" in log.path.read_text(encoding="utf-8")
