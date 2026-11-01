import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tony.core.config.placeholders import MASK, SecretMasker
from tony.core.config.secrets import SECRET_NAME
from tony.core.events.messages import Ruling, ToolCall
from tony.core.logging.task_log import Clock, utc_now

AUDIT_FILE = "logs/audit.jsonl"
PREVIEW_LIMIT = 200
ELLIPSIS = "…"


def canonical_json(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


def args_hash(args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(args).encode()).hexdigest()


def args_preview(args: dict[str, Any], masker: SecretMasker) -> str:
    preview = canonical_json(masker.mask_json(_mask_secret_keys(args)))
    if len(preview) > PREVIEW_LIMIT:
        return preview[:PREVIEW_LIMIT] + ELLIPSIS
    return preview


def _mask_secret_keys(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: MASK if SECRET_NAME.search(key) else _mask_secret_keys(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_mask_secret_keys(item) for item in node]
    return node


class AuditLog:
    """Append-only trail of guard rulings, one JSON line per judged call."""

    def __init__(self, root: Path, *, clock: Clock = utc_now) -> None:
        self.path = root / AUDIT_FILE
        self._clock = clock

    def append(
        self, call: ToolCall, ruling: Ruling, *, args_preview: str, duration_ms: int
    ) -> None:
        line = {
            "ts": self._clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_id": call.task_id,
            "agent": call.agent,
            "tool": call.tool,
            "args_hash": args_hash(call.args),
            "args_preview": args_preview,
            **ruling.model_dump(),
            "duration_ms": duration_ms,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


AuditLine = dict[str, Any]


def read_audit(root: Path) -> tuple[list[AuditLine], int]:
    """Audit lines in file order, plus how many lines were skipped as malformed."""
    path = root / AUDIT_FILE
    if not path.is_file():
        return [], 0
    lines: list[AuditLine] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            lines.append(parsed)
        else:
            malformed += 1
    return lines, malformed


def select_lines(
    lines: list[AuditLine], *, verdict: str | None = None, local_day_of: datetime | None = None
) -> list[AuditLine]:
    """Filter by verdict and, with `local_day_of`, by its local calendar date."""
    selected = [line for line in lines if verdict is None or line.get("verdict") == verdict]
    if local_day_of is None:
        return selected
    return [line for line in selected if _local_date(line, local_day_of) == local_day_of.date()]


def _local_date(line: AuditLine, now: datetime) -> date | None:
    try:
        return datetime.fromisoformat(line["ts"]).astimezone(now.tzinfo).date()
    except (KeyError, TypeError, ValueError):
        return None
