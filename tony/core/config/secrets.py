import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = "config/.env"
SECRET_NAME = re.compile(r"(?i)(token|key|secret|password|passwd|authorization|pin)")


class _EnvFile(BaseSettings):
    model_config = SettingsConfigDict(extra="allow", case_sensitive=True)


@dataclass(frozen=True)
class Variables:
    values: Mapping[str, str]
    env_file_values: Mapping[str, str]
    secret_names: frozenset[str]


def load_variables(root: Path, environ: Mapping[str, str] = os.environ) -> Variables:
    from_file = _EnvFile(_env_file=root / ENV_FILE).model_extra or {}
    env_file_values = {name: value for name, value in from_file.items() if value}
    values = {**from_file, **environ}
    looks_secret = {name for name in values if SECRET_NAME.search(name)}
    return Variables(
        values=values,
        env_file_values=env_file_values,
        secret_names=frozenset(env_file_values) | looks_secret,
    )


def resolve_home(environ: Mapping[str, str] = os.environ) -> Path:
    home = environ.get("TONY_HOME")
    return Path(home) if home else Path.cwd()
