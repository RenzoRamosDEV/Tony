"""Local engine preferences; credentials never enter settings dumps or API responses."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import SecretStr

from tony.core.config.settings import ConfigError, EngineProfile, TonySettings

BUILTINS = {
    "claude-account": EngineProfile(type="claude_sdk", auth="account"),
    "openai-api": EngineProfile(type="litellm", auth="api_key", model="openai/gpt-4o"),
    "anthropic-api": EngineProfile(
        type="litellm", auth="api_key", model="anthropic/claude-sonnet-4-6"
    ),
}
API_PROVIDERS = {"openai-api": "openai", "anthropic-api": "anthropic"}


def load_engine_auth(settings: TonySettings, path: Path) -> None:
    for name, profile in BUILTINS.items():
        if name in settings.engines:
            raise ConfigError(f"El nombre de motor '{name}' está reservado para la interfaz.")
        settings.engines[name] = profile.model_copy(deep=True)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        active = data.get("active")
        if active is not None and active not in settings.engines:
            raise ValueError("perfil inexistente")
        for name, value in data.get("api", {}).items():
            if name not in API_PROVIDERS:
                raise ValueError("proveedor inválido")
            model = validate_api_model(name, value["model"])
            key = value.get("key")
            settings.engines[name] = settings.engines[name].model_copy(
                update={
                    "model": model,
                    "api_key": SecretStr(key) if key else None,
                }
            )
        settings.selected_engine = active
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ConfigError("Configuración local de motores inválida.") from exc


def validate_api_model(name: str, model: str) -> str:
    provider = API_PROVIDERS[name]
    model = model.strip()
    if not model or len(model) > 200 or any(c.isspace() for c in model):
        raise ValueError("Indica un identificador de modelo válido.")
    if "/" not in model:
        model = f"{provider}/{model}"
    if not model.startswith(f"{provider}/") or model == f"{provider}/":
        raise ValueError("El modelo debe pertenecer al proveedor seleccionado.")
    return model


def save_engine_auth(settings: TonySettings, path: Path) -> None:
    data = {
        "active": settings.selected_engine,
        "api": {
            name: {
                "model": profile.model,
                "key": profile.api_key.get_secret_value() if profile.api_key else None,
            }
            for name, profile in settings.engines.items()
            if name in API_PROVIDERS
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".engine-auth-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
