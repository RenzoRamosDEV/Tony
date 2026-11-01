import os
from collections.abc import Mapping
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = "config/.env"


class _EnvFile(BaseSettings):
    model_config = SettingsConfigDict(extra="allow", case_sensitive=True)


def load_secrets(root: Path, environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    from_file = _EnvFile(_env_file=root / ENV_FILE).model_extra or {}
    return {**from_file, **environ}


def resolve_home(environ: Mapping[str, str] = os.environ) -> Path:
    home = environ.get("TONY_HOME")
    return Path(home) if home else Path.cwd()
