"""Persistent user settings (memory/settings.json): read tolerantly, written atomically."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError

from tony.core.config import REPLY_MODES, ReplyMode
from tony.core.memory.atomic import write_atomic

logger = logging.getLogger(__name__)


class UserSettings(BaseModel):
    reply_mode: ReplyMode | None = None


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        raw = self.path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("debe ser un objeto JSON")
            return UserSettings.model_validate(data)
        except (ValueError, ValidationError) as exc:
            logger.warning("settings.json ignorado (%s): %s", exc, raw.strip())
            return UserSettings()

    def set_reply_mode(self, mode: str) -> None:
        if mode not in REPLY_MODES:
            raise ValueError(f"modo '{mode}' no válido; valores: {', '.join(REPLY_MODES)}")
        settings = self.load().model_copy(update={"reply_mode": mode})
        write_atomic(self.path, json.dumps(settings.model_dump(exclude_none=True)))
