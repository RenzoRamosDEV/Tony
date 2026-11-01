import pytest

from tests.core.guard.edith_helpers import audit_lines, call, make_edith
from tony.core.events.messages import Ruling
from tony.core.guard.port import Guard


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("filesystem.read_file", Ruling(verdict="allow", rule="filesystem.read_*/allow")),
        ("shell.run", Ruling(verdict="deny", rule="shell.run/deny")),
    ],
)
async def test_allow_and_deny_need_no_confirmation(tmp_path, tool, expected):
    edith, confirmer = make_edith(tmp_path)

    ruling = await edith.decide(call(tool, {"path": "a.md"}))

    assert ruling == expected
    assert confirmer.questions == []


async def test_one_exact_audit_line_per_verdict(tmp_path):
    edith, _ = make_edith(tmp_path, readings=(10.0, 10.0042))

    await edith.decide(call("shell.run", {"command": "sudo x", "token": "abc123"}))

    assert audit_lines(tmp_path) == [
        {
            "ts": "2026-11-01T09:00:00Z",
            "task_id": "t" * 32,
            "agent": "viernes",
            "tool": "shell.run",
            "args_hash": audit_lines(tmp_path)[0]["args_hash"],
            "args_preview": '{"command": "sudo x", "token": "***"}',
            "verdict": "deny",
            "rule": "shell.run/deny",
            "user_decision": None,
            "duration_ms": 4,
        }
    ]
    assert len(audit_lines(tmp_path)[0]["args_hash"]) == 64


async def test_env_secret_masked_in_audit_preview(tmp_path):
    edith, _ = make_edith(tmp_path)

    await edith.decide(call("filesystem.read_file", {"q": "x s3cr3t"}))

    [line] = audit_lines(tmp_path)
    assert line["args_preview"] == '{"q": "x ***"}'
    assert "s3cr3t" not in (tmp_path / "logs" / "audit.jsonl").read_text()


async def test_each_call_appends_its_own_line(tmp_path):
    edith, _ = make_edith(tmp_path, readings=(0, 0, 0, 0))

    await edith.decide(call("filesystem.read_file"))
    await edith.decide(call("shell.run"))

    assert [line["verdict"] for line in audit_lines(tmp_path)] == ["allow", "deny"]


def test_satisfies_guard_port(tmp_path):
    assert isinstance(make_edith(tmp_path)[0], Guard)
