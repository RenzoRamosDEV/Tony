import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tony.core.config.placeholders import SecretMasker

Clock = Callable[[], datetime]


def new_task_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> datetime:
    return datetime.now(UTC)


class JsonlTaskLog:
    def __init__(
        self,
        root: Path,
        task_id: str,
        *,
        masker: SecretMasker | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.task_id = task_id
        self.path = root / "logs" / "tasks" / f"{task_id}.jsonl"
        self._masker = masker or SecretMasker()
        self._clock = clock

    def emit(self, event: dict[str, Any]) -> None:
        envelope = {"ts": self._clock().astimezone(UTC).isoformat(), "task_id": self.task_id}
        envelope |= {key: value for key, value in event.items() if key not in envelope}
        line = json.dumps(self._masker.mask_json(envelope), ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
