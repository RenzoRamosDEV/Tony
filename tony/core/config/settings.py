"""Global Tony settings loaded from config/tony.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

ReplyMode = Literal["auto", "voice", "text", "both"]
REPLY_MODES: tuple[str, ...] = get_args(ReplyMode)

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


DEFAULT_ACKNOWLEDGEMENTS = [
    "Un momento, señor.",
    "Enseguida, señor.",
    "Ahora mismo lo reviso, señor.",
]
MAX_ACKNOWLEDGEMENT_CHARS = 60
VOICE_RANGES: dict[str | None, tuple[float, float]] = {
    "end_silence_ms": (300, 1500),
    "barge_in_threshold": (0.5, 0.99),
    "barge_in_min_speech_ms": (150, 1000),
    "cpu_threads": (1, 64),
}


class VoiceSettings(StrictModel):
    stt: str = "faster-whisper/base"
    tts: str = "piper/es_MX-ald-medium?speed=0.95"
    vad: str = "silero"
    end_silence_ms: int = 500
    barge_in: bool = True
    barge_in_threshold: float = 0.8
    barge_in_min_speech_ms: int = 280
    cpu_threads: int | None = None
    acknowledgements: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ACKNOWLEDGEMENTS), min_length=1, max_length=10
    )

    @field_validator(
        "end_silence_ms", "barge_in_threshold", "barge_in_min_speech_ms", "cpu_threads"
    )
    @classmethod
    def must_be_in_range(cls, value: float | None, info: ValidationInfo) -> float | None:
        low, high = VOICE_RANGES[info.field_name]
        if value is not None and not low <= value <= high:
            raise ValueError(f"debe estar entre {low} y {high}")
        return value

    @field_validator("acknowledgements")
    @classmethod
    def acknowledgements_must_be_short_phrases(cls, value: list[str]) -> list[str]:
        for phrase in value:
            if not phrase.strip():
                raise ValueError("cada acuse debe ser una frase no vacía")
            if len(phrase) > MAX_ACKNOWLEDGEMENT_CHARS:
                raise ValueError(
                    f"cada acuse debe tener como máximo {MAX_ACKNOWLEDGEMENT_CHARS} caracteres"
                )
        return value


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
