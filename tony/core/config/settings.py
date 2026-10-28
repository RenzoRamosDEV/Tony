"""Global Tony settings loaded from config/tony.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

ReplyMode = Literal["auto", "voice", "text", "both"]

DEFAULT_MODELS: dict[str, str] = {
    "claude-haiku": "claude-haiku-5-5",
    "claude-sonnet": "claude-sonnet-5-5",
}


class ConfigError(Exception):
    """Invalid configuration; the message names the offending field path."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Limits(StrictModel):
    tool_timeout_s: float = 20
    task_timeout_s: float = 300
    confirm_timeout_s: float = 60
    mcp_connect_timeout_s: float = 10
    token_alert: int = 50000
    memory_max_lines: int = 200


class WebSettings(StrictModel):
    port: int = 8787
    host: str = "127.0.0.1"


class VoiceSettings(StrictModel):
    stt: str = "faster-whisper/small"
    tts: str = "kokoro/ef_dora"
    vad: str = "silero"


class TonySettings(StrictModel):
    front: str = "jarvis"
    worker: str = "viernes"
    reply_mode: ReplyMode = "auto"
    models: dict[str, str] = dict(DEFAULT_MODELS)
    voice: VoiceSettings = VoiceSettings()
    channels: list[str] = ["cli", "web"]
    web: WebSettings = WebSettings()
    limits: Limits = Limits()

    @field_validator("models", mode="before")
    @classmethod
    def merge_default_models(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError("debe ser un mapa de alias a identificadores de modelo")
        return {**DEFAULT_MODELS, **value}

    @model_validator(mode="after")
    def front_and_worker_must_differ(self) -> TonySettings:
        if self.front == self.worker:
            raise ValueError("front y worker deben ser agentes distintos")
        return self


def load_settings(path: Path | None) -> TonySettings:
    """Build settings from a YAML file; a missing file or None yields the defaults."""
    data = _read_yaml(path) if path is not None else {}
    try:
        return TonySettings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido: {exc}") from None
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError("config: debe ser un mapa YAML")
    return loaded


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "config"
        lines.append(f"{location}: {error['msg']}")
    return "; ".join(lines)
