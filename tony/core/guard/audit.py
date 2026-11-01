import hashlib
import json
from datetime import UTC
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
            **ruling.model_dump(mode="json"),
            "duration_ms": duration_ms,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
