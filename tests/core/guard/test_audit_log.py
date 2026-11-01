import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import Ruling, ToolCall
from tony.core.guard.audit import AUDIT_FILE, AuditLog, args_preview

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "audit_confirm.jsonl"
CALL = ToolCall(
    task_id="3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b",
    agent="viernes",
    tool="filesystem.delete_file",
    args={"path": "/home/renzo/notas/viejo.md"},
)
CONFIRMED = Ruling(verdict="confirm", rule="filesystem.delete*/confirm", user_decision="allow")


def fixed_clock():
    return datetime(2026, 11, 1, 10, 15, 2, 345678, tzinfo=UTC)


class TestArgsPreview:
    def test_secret_looking_keys_masked(self):
        preview = args_preview({"path": "a.md", "api_key": "abc123"}, SecretMasker())

        assert preview == '{"api_key": "***", "path": "a.md"}'

    def test_nested_secret_keys_masked_whole_value(self):
        args = {"opts": {"Token": {"v": "abc123"}, "list": [{"password": "p4ss", "n": 1}]}}

        preview = args_preview(args, SecretMasker())

        assert preview == '{"opts": {"Token": "***", "list": [{"n": 1, "password": "***"}]}}'

    def test_env_values_masked(self):
        preview = args_preview({"q": "token s3cr3t"}, SecretMasker({"s3cr3t"}))

        assert preview == '{"q": "token ***"}'

    def test_home_path_unmasked(self):
        preview = args_preview({"path": "/home/renzo/notas/a.md"}, SecretMasker({"s3cr3t"}))

        assert preview == '{"path": "/home/renzo/notas/a.md"}'

    def test_does_not_mutate_args(self):
        args = {"api_key": "abc123", "nested": {"token": "t"}}

        args_preview(args, SecretMasker())

        assert args == {"api_key": "abc123", "nested": {"token": "t"}}

    @pytest.mark.parametrize(("length", "truncated"), [(199, False), (200, False), (201, True)])
    def test_truncation_boundary(self, length, truncated):
        args = {"q": "x" * (length - len('{"q": ""}'))}
        canonical = json.dumps(args)
        assert len(canonical) == length

        preview = args_preview(args, SecretMasker())

        assert preview == (canonical[:200] + "…" if truncated else canonical)


class TestAuditLog:
    def test_confirmed_delete_matches_golden(self, tmp_path):
        log = AuditLog(tmp_path, clock=fixed_clock)

        log.append(
            CALL, CONFIRMED, args_preview=args_preview(CALL.args, SecretMasker()), duration_ms=8423
        )

        assert (tmp_path / AUDIT_FILE).read_text() == GOLDEN.read_text()

    def test_creates_logs_folder_and_appends_one_line_per_call(self, tmp_path):
        log = AuditLog(tmp_path, clock=fixed_clock)
        denied = Ruling(verdict="deny", rule="default")

        log.append(CALL, CONFIRMED, args_preview="p1", duration_ms=1)
        log.append(CALL, denied, args_preview="p2", duration_ms=0)

        lines = [json.loads(line) for line in (tmp_path / "logs" / "audit.jsonl").open()]
        assert [line["args_preview"] for line in lines] == ["p1", "p2"]
        assert lines[1] | {"ts": None} == {
            "ts": None,
            "task_id": CALL.task_id,
            "agent": "viernes",
            "tool": "filesystem.delete_file",
            "args_hash": "3fb94b7182a489ba6013f13de24e78cca69b1e373e8281c9035a78255be91b5e",
            "args_preview": "p2",
            "verdict": "deny",
            "rule": "default",
            "user_decision": None,
            "duration_ms": 0,
        }

    def test_ts_converted_to_utc(self, tmp_path):
        plus_one = timezone(timedelta(hours=1))
        log = AuditLog(tmp_path, clock=lambda: datetime(2026, 11, 1, 0, 30, tzinfo=plus_one))

        log.append(CALL, CONFIRMED, args_preview="p", duration_ms=1)

        line = json.loads((tmp_path / AUDIT_FILE).read_text())
        assert line["ts"] == "2026-10-31T23:30:00Z"

    def test_non_ascii_written_as_is(self, tmp_path):
        log = AuditLog(tmp_path, clock=fixed_clock)

        log.append(CALL, CONFIRMED, args_preview='{"q": "acción"}', duration_ms=1)

        assert "acción" in (tmp_path / AUDIT_FILE).read_text(encoding="utf-8")
