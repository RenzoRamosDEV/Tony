"""Credential storage and authentication boundaries without paid provider calls."""

import json
import os

import pytest
from pydantic import SecretStr

from tony.core.config import TonySettings
from tony.core.config.engine_auth import load_engine_auth, save_engine_auth, validate_api_model
from tony.core.runner.auth import account_env, claude_account_options, codex_account_args


def test_credentials_roundtrip_private_and_excluded_from_settings(tmp_path):
    path = tmp_path / "engine-auth.json"
    settings = TonySettings()
    load_engine_auth(settings, path)
    settings.engines["openai-api"].api_key = SecretStr("secret-test-key")
    settings.selected_engine = "openai-api"
    save_engine_auth(settings, path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert "secret-test-key" not in settings.model_dump_json()
    assert "secret-test-key" not in repr(settings)
    restored = TonySettings()
    load_engine_auth(restored, path)
    assert restored.selected_engine == "openai-api"
    assert restored.engines["openai-api"].api_key.get_secret_value() == "secret-test-key"
    restored.engines["openai-api"].api_key = None
    save_engine_auth(restored, path)
    assert "secret-test-key" not in path.read_text()
    assert not list(tmp_path.glob(".engine-auth-*"))


@pytest.mark.parametrize("model", ["", " ", "anthropic/other", "openai/", "openai/a b"])
def test_api_models_cannot_select_another_provider(model):
    with pytest.raises(ValueError):
        validate_api_model("openai-api", model)


def test_account_credentials_are_isolated_from_api_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "another-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    settings = TonySettings()
    load_engine_auth(settings, tmp_path / "engine-auth.json")
    options = claude_account_options(settings.engines["claude-account"])
    assert options["env"]["ANTHROPIC_API_KEY"] == ""
    assert options["env"]["CLAUDE_CODE_USE_BEDROCK"] == ""
    assert json.loads(options["settings"])["forceLoginMethod"] == "claudeai"
    assert "OPENAI_API_KEY" not in account_env("codex_cli")
    assert 'forced_login_method="chatgpt"' in codex_account_args(settings.engines["codex-account"])
    assert os.environ["OPENAI_API_KEY"] == "another-key"


@pytest.mark.parametrize(
    "engine,status,valid",
    [
        ("codex-account", b"Logged in using ChatGPT", True),
        ("codex-account", b"Logged in using an API key", False),
        ("claude-account", b'{"loggedIn":true,"authMethod":"claude.ai"}', True),
        ("claude-account", b'{"loggedIn":true,"authMethod":"api_key"}', False),
        ("claude-account", b'{"loggedIn":false}', False),
    ],
)
async def test_account_selection_requires_account_login(
    tmp_path, monkeypatch, engine, status, valid
):
    from tony.core.runner import auth

    class StatusProcess:
        returncode = 0

        async def communicate(self):
            return status, b""

    async def launch(*args, **kwargs):
        assert kwargs["env"].get("OPENAI_API_KEY", "") != "env-key"
        return StatusProcess()

    settings = TonySettings()
    load_engine_auth(settings, tmp_path / "engine-auth.json")
    monkeypatch.setattr(auth.asyncio, "create_subprocess_exec", launch)
    if valid:
        await auth.require_credentials(settings.engines[engine])
    else:
        with pytest.raises(ValueError, match="Inicia sesión"):
            await auth.require_credentials(settings.engines[engine])
