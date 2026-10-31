"""Explicit account authentication without changing the parent's environment."""

from __future__ import annotations

import asyncio
import json
import os

from tony.core.config.settings import EngineProfile

CLAUDE_API_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def account_env(engine: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    if engine == "claude_sdk":
        # SDK merges its env with the parent's, so explicit empty overrides are needed.
        for name in CLAUDE_API_ENV:
            env[name] = ""
    return env


def claude_account_options(profile: EngineProfile) -> dict:
    if profile.auth != "account":
        return {}
    return {
        "env": account_env("claude_sdk", {}),
        "settings": json.dumps(
            {
                "forceLoginMethod": "claudeai",
                "apiKeyHelper": "",
            }
        ),
    }


async def require_credentials(profile: EngineProfile) -> None:
    if profile.auth == "api_key":
        if not profile.api_key:
            raise ValueError("Configura una API key antes de seleccionar este motor.")
        return
    if profile.auth != "account":
        return
    argv = [
        "claude",
        "--setting-sources",
        "",
        "--settings",
        json.dumps({"forceLoginMethod": "claudeai", "apiKeyHelper": ""}),
        "auth",
        "status",
        "--json",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=account_env(profile.type),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            proc.kill()
            await proc.wait()
            raise
        status = json.loads(stdout)
        valid = (
            proc.returncode == 0
            and isinstance(status, dict)
            and status.get("loggedIn")
            and status.get("authMethod") == "claude.ai"
        )
        if valid:
            return
    except (OSError, ValueError, TimeoutError):
        pass
    raise ValueError("Inicia sesión con tu cuenta en el equipo de Tony: claude auth login")
