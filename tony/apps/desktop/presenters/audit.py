"""Today's Edith audit rows for the page, without tool arguments (read-only file access)."""

from datetime import datetime
from pathlib import Path
from typing import Any

from tony.core.guard.audit import AuditLine, read_audit, select_lines

AuditRow = dict[str, Any]


def audit_today(root: Path, now: datetime) -> list[AuditRow]:
    lines, _ = read_audit(root)
    return [_row(line, now) for line in select_lines(lines, local_day_of=now)]


def _row(line: AuditLine, now: datetime) -> AuditRow:
    local = datetime.fromisoformat(line["ts"]).astimezone(now.tzinfo)
    return {
        "time": local.strftime("%H:%M:%S"),
        "agent": line["agent"],
        "tool": line["tool"],
        "verdict": line["verdict"],
        "rule": line["rule"],
        "user_decision": line["user_decision"],
    }
