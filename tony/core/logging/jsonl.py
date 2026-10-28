"""Append-only JSONL log, one file per task.

Event contract (schema_version 1), one JSON object per line:

    {"schema_version": 1, "ts": "<ISO-8601 UTC, ms, Z>", "task_id": "<hex>",
     "seq": <int from 1>, "type": "<event type>", "payload": {...}}

Subtasks add `"parent_id": "<hex>"` after `task_id`; root tasks omit the key.

Files live at logs/<YYYYMMDD>/<task_id>.jsonl (UTC date of the first event). The sink
assigns `ts` and `seq`, redacts secrets, and flushes after every event.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from tony.core.logging.redact import redact

SCHEMA_VERSION = 1


def utc_timestamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonlEventSink:
    def __init__(
        self,
        logs_dir: Path,
        task_id: str,
        secrets: Iterable[str],
        parent_id: str | None = None,
    ) -> None:
        self._task_id = task_id
        self._parent_id = parent_id
        self._secrets = list(secrets)
        self._seq = 0
        self._file: TextIO | None = None
        self._closed = False
        self.path = logs_dir / datetime.now(UTC).strftime("%Y%m%d") / f"{task_id}.jsonl"

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        file = self._open()
        if file is None:
            return
        self._seq += 1
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "ts": utc_timestamp(),
            "task_id": self._task_id,
        }
        if self._parent_id is not None:
            record["parent_id"] = self._parent_id
        record.update(
            {"seq": self._seq, "type": event_type, "payload": redact(payload, self._secrets)}
        )
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
        file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self._closed = True

    def _open(self) -> TextIO | None:
        if self._closed:
            return None
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a", encoding="utf-8")
        return self._file
