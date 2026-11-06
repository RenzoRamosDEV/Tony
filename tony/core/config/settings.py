import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tony.core.config.errors import DefinitionError

CONFIG_FILE = "config/tony.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceSettings(_Strict):
    stt: str = "faster-whisper/small"
    vad: str = "silero"
    tts_default: str = "kokoro/em_alex"
    input_device: str | None = None
    output_device: str | None = None


class DesktopSettings(_Strict):
    hotkey: str = "Super+J"
    tray: bool = True
    theme: str = "system"


class TonyConfig(_Strict):
    front: str = "jarvis"
    worker: str = "viernes"
    guard: str = "edith"
    reply_mode: Literal["auto", "voice", "text", "both"] = "auto"
    models: dict[str, str] = Field(
        default_factory=lambda: {
            "claude-haiku": "claude-haiku-5-5",
            "claude-sonnet": "claude-sonnet-5-5",
        }
    )
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    desktop: DesktopSettings = Field(default_factory=DesktopSettings)

    def resolve_model(self, alias: str) -> str:
        try:
            return self.models[alias]
        except KeyError:
            raise DefinitionError(CONFIG_FILE, "models", f"unknown model alias '{alias}'") from None


def load_config(root: Path) -> TonyConfig:
    path = root / CONFIG_FILE
    if not path.exists():
        return TonyConfig()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as error:
        raise DefinitionError(CONFIG_FILE, None, f"invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise DefinitionError(CONFIG_FILE, None, "must be a YAML mapping")
    try:
        return TonyConfig.model_validate(data)
    except ValidationError as error:
        raise DefinitionError.from_validation(CONFIG_FILE, error) from error


def save_config(root: Path, config: TonyConfig) -> None:
    path = root / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix=".tony.yaml.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config.model_dump(), handle)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
