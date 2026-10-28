"""Load agents from agents/<name>/ folders."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tony.core.config import EnvMap, TonySettings
from tony.core.loader.errors import AgentLoadError, MissingEnvVar
from tony.core.loader.frontmatter import FrontmatterError, split_frontmatter
from tony.core.loader.models import AgentSpec, ToolConfig
from tony.core.loader.substitution import substitute_deep

SUBSTITUTED_FIELDS = ("args", "env", "url", "headers")
RESERVED_HEADER_KEYS = frozenset({"system_prompt", "path", "tools", "secrets"})


def load_agent(path: Path, settings: TonySettings, env: EnvMap) -> AgentSpec:
    """Load agents/<name>/agent.md and tool/tool.json into an AgentSpec."""
    agent = path.name
    agent_md = path / "agent.md"
    if not agent_md.is_file():
        raise AgentLoadError(agent, f"no existe {agent_md}")
    try:
        header, body = split_frontmatter(agent_md.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise AgentLoadError(agent, str(exc)) from None
    reserved = sorted(RESERVED_HEADER_KEYS & header.keys())
    if reserved:
        raise AgentLoadError(agent, f"el frontmatter no puede definir {reserved}")
    tools, secrets = _load_tool_config(path / "tool" / "tool.json", agent, env)
    try:
        spec = AgentSpec.model_validate(
            {**header, "system_prompt": body, "path": path, "tools": tools, "secrets": secrets}
        )
    except ValidationError as exc:
        raise AgentLoadError(agent, _format_validation_error(exc)) from None
    if spec.model not in settings.models:
        raise AgentLoadError(
            agent,
            f"alias de modelo desconocido '{spec.model}'; disponibles: {sorted(settings.models)}",
        )
    return spec


def load_all(
    agents_dir: Path, settings: TonySettings, env: EnvMap
) -> dict[str, AgentSpec | AgentLoadError]:
    """Load every subfolder of agents_dir; a broken agent yields its error instead."""
    result: dict[str, AgentSpec | AgentLoadError] = {}
    for folder in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
        try:
            result[folder.name] = load_agent(folder, settings, env)
        except AgentLoadError as exc:
            result[folder.name] = exc
    return result


class _RecordingEnv(Mapping[str, str]):
    """Read-through view of the environment that remembers every value handed out."""

    def __init__(self, env: EnvMap) -> None:
        self._env = env
        self.used_values: list[str] = []

    def __getitem__(self, key: str) -> str:
        value = self._env[key]
        if value not in self.used_values:
            self.used_values.append(value)
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._env)

    def __len__(self) -> int:
        return len(self._env)


def _load_tool_config(tool_json: Path, agent: str, env: EnvMap) -> tuple[ToolConfig, list[str]]:
    if not tool_json.is_file():
        return ToolConfig(), []
    try:
        raw = json.loads(tool_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentLoadError(agent, f"tool.json inválido: {exc}") from None
    if not isinstance(raw, dict):
        raise AgentLoadError(agent, "tool.json: debe ser un objeto JSON")
    recording = _RecordingEnv(env)
    try:
        raw["mcpServers"] = _substitute_servers(raw.get("mcpServers", {}), recording)
        return ToolConfig.model_validate(raw), recording.used_values
    except MissingEnvVar as exc:
        raise AgentLoadError(agent, str(exc)) from None
    except ValidationError as exc:
        raise AgentLoadError(agent, f"tool.json: {_format_validation_error(exc)}") from None


def _substitute_servers(servers: Any, env: Mapping[str, str]) -> Any:
    if not isinstance(servers, dict):
        return servers
    substituted = {}
    for name, server in servers.items():
        if not isinstance(server, dict):
            substituted[name] = server
            continue
        try:
            substituted[name] = {
                key: substitute_deep(value, env) if key in SUBSTITUTED_FIELDS else value
                for key, value in server.items()
            }
        except MissingEnvVar as exc:
            raise MissingEnvVar(exc.var, name) from None
    return substituted


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)
