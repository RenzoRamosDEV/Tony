"""Installation checks of `tony doctor`: pure functions over injected dependencies."""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from tony.core.config import ConfigError, EnvMap, TonySettings, load_env, load_settings
from tony.core.doctor.validate import CheckResult, validate_agent
from tony.core.loader import AgentLoadError, AgentSpec, StdioServer, ToolConfig, load_all
from tony.core.mcp import McpManager, McpServerStatus, ToolCatalog
from tony.core.runner.oneshot import one_shot
from tony.core.voice.aliases import ENGINES_FOR_KEY, alias_problem
from tony.core.voice.engines import EXTRA_HINT, REQUIRED_MODULES

REQUIRED_PYTHON = (3, 12)
PROBE_PROMPT = "Responde exactamente: OK"
PROBE_MODEL = "claude-haiku"
NODE_COMMANDS = frozenset({"npx", "node"})
GROUP_OR_OTHER_READABLE = stat.S_IRWXG | stat.S_IRWXO
ESPEAK_HINT = "rpm-ostree install espeak-ng o brew install espeak-ng"
WARMUP_HINT = "ejecuta tony voice warmup"
KOKORO_MODEL_DIR = "models--hexgrad--Kokoro-82M"
PIPER_MODEL_DIR = "models--rhasspy--piper-voices"
TTS_MODEL_DIRS = {
    "kokoro": ("Kokoro-82M", KOKORO_MODEL_DIR),
    "piper": ("piper-voices", PIPER_MODEL_DIR),
}
WHISPER_MODEL_DIR = "models--Systran--faster-whisper-{size}"


def default_model_cache() -> Path:
    return Path(os.environ.get("HF_HUB_CACHE") or Path.home() / ".cache" / "huggingface" / "hub")


@dataclass(frozen=True)
class DoctorPaths:
    config_path: Path
    agents_dir: Path

    @property
    def dotenv(self) -> Path:
        return self.config_path.parent / ".env"


ConnectResult = tuple[dict[str, McpServerStatus], ToolCatalog]


async def probe_model(settings: TonySettings) -> str:
    reply = await one_shot(settings, PROBE_MODEL, PROBE_PROMPT)
    return str(reply)


async def connect_mcp(settings: TonySettings, tools: ToolConfig) -> ConnectResult:
    manager = McpManager(connect_timeout_s=settings.limits.mcp_connect_timeout_s)
    try:
        await manager.start(tools)
        return manager.status(), manager.catalog
    finally:
        await manager.stop()


@dataclass(frozen=True)
class Environment:
    which: Callable[[str], str | None] = shutil.which
    python_version: tuple[int, int] = field(default_factory=lambda: tuple(sys.version_info[:2]))
    find_spec: Callable[[str], Any] = importlib.util.find_spec
    probe_model: Callable[[TonySettings], Awaitable[str]] = probe_model
    connect_mcp: Callable[[TonySettings, ToolConfig], Awaitable[ConnectResult]] = connect_mcp
    model_cache: Path = field(default_factory=default_model_cache)


async def run_checks(
    paths: DoctorPaths,
    env: Environment,
    offline: bool,
    connect: bool,
    *,
    check_external: bool = True,
) -> list[CheckResult]:
    results = [check_python(env), check_claude_cli(env)]
    settings_result, settings = check_settings(paths)
    results.append(settings_result)
    results.append(await check_model(env, settings, offline))
    results.append(check_dotenv(paths))
    agents = load_agents(paths, settings)
    results.extend(check_agents(paths, agents, settings))
    profiles = {spec.engine for _, spec in _specs(agents)}
    used_settings = settings.model_copy(
        update={
            "engines": {
                name: profile for name, profile in settings.engines.items() if name in profiles
            }
        }
    )
    if check_external and any(
        profile.type == "codex_cli" for profile in used_settings.engines.values()
    ):
        results.append(
            CheckResult("codex_cli", None, "omitido (--offline)")
            if offline
            else check_codex_cli(env)
        )
    results.extend(check_litellm(used_settings, load_env(paths.dotenv)))
    results.append(check_node(env, agents))
    results.extend(check_voice(env, settings))
    if connect:
        results.extend(await check_servers(env, settings, agents))
    return results


def exit_code(results: Iterable[CheckResult]) -> int:
    return 1 if any(r.failed for r in results) else 0


def check_python(env: Environment) -> CheckResult:
    version = ".".join(str(part) for part in env.python_version)
    if tuple(env.python_version) == REQUIRED_PYTHON:
        return CheckResult("python", True, version)
    return CheckResult(
        "python",
        False,
        f"versión {version}",
        "usa Python 3.12 (por ejemplo: uv python install 3.12)",
    )


def check_claude_cli(env: Environment) -> CheckResult:
    path = env.which("claude")
    if path:
        return CheckResult("claude", True, path)
    return CheckResult(
        "claude",
        False,
        "el CLI 'claude' no está en el PATH",
        "instala Claude Code CLI y autentícalo con `claude login`",
    )


def check_codex_cli(env: Environment) -> CheckResult:
    """Check binary availability locally; authentication is not probed."""
    path = env.which("codex")
    if path:
        return CheckResult("codex_cli", True, path)
    return CheckResult(
        "codex_cli",
        False,
        "el CLI 'codex' no está en el PATH",
        "instala Codex CLI y autentícate con `codex login`",
    )


def check_litellm(settings: TonySettings, env: EnvMap) -> list[CheckResult]:
    """Return one local check per LiteLLM profile supplied (caller selects used profiles).

    LiteLLM identifies missing process variables; the merged dotenv map can supply them
    without mutating the process environment or contacting a provider.
    """
    results = []
    for name, profile in settings.engines.items():
        if profile.type != "litellm":
            continue
        label = f"litellm:{name}"
        try:
            import litellm
        except ImportError:
            results.append(
                CheckResult(
                    label,
                    False,
                    "LiteLLM no está instalado",
                    "instala las dependencias con `uv sync`",
                )
            )
            continue
        try:
            validation = litellm.validate_environment(model=profile.model)
        except Exception:  # noqa: BLE001 - report diagnostics without exposing provider secrets
            results.append(
                CheckResult(
                    label,
                    False,
                    f"no se pudo validar el entorno de {profile.model}",
                    f"revisa el modelo del perfil '{name}' en config/tony.yaml",
                )
            )
            continue
        missing = [key for key in validation.get("missing_keys", []) if not env.get(key)]
        if missing:
            variables = ", ".join(missing)
            results.append(
                CheckResult(label, False, f"falta {variables}", f"añade {variables} a config/.env")
            )
        else:
            results.append(CheckResult(label, True, profile.model))
    return results


def check_settings(paths: DoctorPaths) -> tuple[CheckResult, TonySettings]:
    try:
        settings = load_settings(paths.config_path)
    except ConfigError as exc:
        return (
            CheckResult(
                "config/tony.yaml", False, str(exc), "corrige el campo indicado en config/tony.yaml"
            ),
            load_settings(None),
        )
    return (
        CheckResult("config/tony.yaml", True, f"front {settings.front}, worker {settings.worker}"),
        settings,
    )


async def check_model(env: Environment, settings: TonySettings, offline: bool) -> CheckResult:
    if offline:
        return CheckResult("modelo", None, "omitido (--offline)")
    try:
        reply = await env.probe_model(settings)
    except Exception as exc:  # noqa: BLE001 - any failure is a diagnostic, not a crash
        return CheckResult(
            "modelo",
            False,
            f"{PROBE_MODEL} no respondió: {exc}",
            "autentica Claude Code CLI con `claude login` y revisa la red",
        )
    return CheckResult("modelo", True, f"{PROBE_MODEL} respondió: {reply.strip()[:40]}")


def check_dotenv(paths: DoctorPaths) -> CheckResult:
    dotenv = paths.dotenv
    if not dotenv.is_file():
        return CheckResult(
            "config/.env",
            False,
            f"no existe {dotenv}",
            "créalo con permisos 600: touch config/.env && chmod 600 config/.env",
        )
    mode = stat.S_IMODE(dotenv.stat().st_mode)
    if mode & GROUP_OR_OTHER_READABLE:
        return CheckResult(
            "config/.env",
            False,
            f"permisos {mode:03o} (legible por otros)",
            "chmod 600 config/.env",
        )
    return CheckResult("config/.env", True, f"permisos {mode:03o}")


def load_agents(
    paths: DoctorPaths, settings: TonySettings
) -> dict[str, AgentSpec | AgentLoadError]:
    if not paths.agents_dir.is_dir():
        return {}
    env: EnvMap = load_env(paths.dotenv)
    return load_all(paths.agents_dir, settings, env)


def check_agents(
    paths: DoctorPaths, agents: dict[str, AgentSpec | AgentLoadError], settings: TonySettings
) -> list[CheckResult]:
    if not paths.agents_dir.is_dir():
        return [
            CheckResult(
                "agents",
                False,
                f"no existe el directorio {paths.agents_dir}",
                "crea agents/ con un agente por carpeta",
            )
        ]
    env = load_env(paths.dotenv)
    results: list[CheckResult] = []
    for name in agents:
        results.extend(validate_agent(paths.agents_dir, name, settings, env))
    for name in (settings.front, settings.worker):
        if name not in agents:
            results.append(
                CheckResult(
                    f"agente {name}",
                    False,
                    f"no existe la carpeta {paths.agents_dir / name}",
                    f"crea agents/{name}/agent.md o cambia front/worker en config/tony.yaml",
                )
            )
    return results


def check_node(env: Environment, agents: dict[str, AgentSpec | AgentLoadError]) -> CheckResult:
    users = [
        f"{label}/{server}"
        for label, spec in _specs(agents)
        for server, definition in spec.tools.mcpServers.items()
        if isinstance(definition, StdioServer) and definition.command in NODE_COMMANDS
    ]
    if not users:
        return CheckResult("node/npx", None, "ningún MCP usa node/npx; omitido")
    missing = sorted(command for command in NODE_COMMANDS if not env.which(command))
    if missing:
        return CheckResult(
            "node/npx",
            False,
            f"faltan {', '.join(missing)} en el PATH; los usan {', '.join(users)}",
            "instala Node.js (incluye npx), por ejemplo con nvm",
        )
    return CheckResult("node/npx", True, f"disponibles; los usan {', '.join(users)}")


def check_voice(env: Environment, settings: TonySettings) -> list[CheckResult]:
    """Extra, espeak-ng and model cache only inform; an invalid alias is a failure."""
    installed = all(env.find_spec(module) is not None for module in REQUIRED_MODULES)
    extra = (
        "extra tony[voice] instalado"
        if installed
        else f"extra tony[voice] no instalado: {EXTRA_HINT}"
    )
    espeak = env.which("espeak-ng")
    espeak_result = (
        CheckResult("espeak-ng", True, espeak)
        if espeak
        else CheckResult("espeak-ng", None, f"no encontrado (lo necesita la voz): {ESPEAK_HINT}")
    )
    return [
        CheckResult("voice", None, extra),
        espeak_result,
        *check_voice_aliases(settings),
        check_voice_models(env, settings),
    ]


def check_voice_aliases(settings: TonySettings) -> list[CheckResult]:
    results = []
    for key in ENGINES_FOR_KEY:
        alias = getattr(settings.voice, key.split(".")[1])
        problem = alias_problem(key, alias)
        if problem is not None:
            results.append(CheckResult(key, False, problem, f"corrige {key} en config/tony.yaml"))
            continue
        results.append(CheckResult(key, True, alias))
    return results


def check_voice_models(env: Environment, settings: TonySettings) -> CheckResult:
    size = settings.voice.stt.partition("/")[2] or "base"
    tts_engine = settings.voice.tts.partition("/")[0]
    tts_name, tts_dir = TTS_MODEL_DIRS.get(tts_engine, TTS_MODEL_DIRS["piper"])
    wanted = {
        f"faster-whisper-{size}": env.model_cache / WHISPER_MODEL_DIR.format(size=size),
        tts_name: env.model_cache / tts_dir,
    }
    missing = [name for name, path in wanted.items() if not path.is_dir()]
    if not missing:
        return CheckResult("voice-models", True, f"{' y '.join(wanted)} en caché")
    if len(missing) == len(wanted):
        return CheckResult("voice-models", None, f"modelos de voz no descargados: {WARMUP_HINT}")
    return CheckResult(
        "voice-models", None, f"falta {', '.join(missing)} en la caché: {WARMUP_HINT}"
    )


async def check_servers(
    env: Environment, settings: TonySettings, agents: dict[str, AgentSpec | AgentLoadError]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for label, spec in _specs(agents):
        if not spec.tools.mcpServers:
            continue
        unfiltered = ToolConfig(mcpServers=spec.tools.mcpServers)
        statuses, catalog = await env.connect_mcp(settings, unfiltered)
        results.extend(_server_results(label, statuses))
        ready = {name for name, status in statuses.items() if status.state == "ready"}
        results.extend(_pattern_results(label, spec.tools, catalog, ready))
    return results


def _server_results(label: str, statuses: dict[str, McpServerStatus]) -> list[CheckResult]:
    results = []
    for name, status in statuses.items():
        if status.state == "ready":
            results.append(CheckResult(f"mcp {label}/{name}", True, f"{status.tool_count} tools"))
        else:
            results.append(
                CheckResult(
                    f"mcp {label}/{name}",
                    False,
                    status.error or "error",
                    f"revisa command/url del servidor '{name}' en tool.json",
                )
            )
    return results


def _pattern_results(
    label: str, tools: ToolConfig, catalog: ToolCatalog, ready: set[str]
) -> list[CheckResult]:
    names = catalog.qualified_names()
    results = []
    for pattern in [*(tools.allow or []), *tools.confirm]:
        if pattern.partition(".")[0] not in ready:
            continue
        if not any(fnmatchcase(name, pattern) for name in names):
            results.append(
                CheckResult(
                    f"patrón {label}/{pattern}",
                    False,
                    "no coincide con ninguna tool del servidor",
                    "revisa allow/confirm en tool.json",
                )
            )
    return results


def _specs(agents: dict[str, AgentSpec | AgentLoadError]) -> list[tuple[str, AgentSpec]]:
    pairs: list[tuple[str, AgentSpec]] = []
    for name, spec in agents.items():
        if isinstance(spec, AgentLoadError):
            continue
        pairs.append((name, spec))
        pairs.extend(
            (f"{name}/{child}", child_spec) for child, child_spec in spec.subagents.items()
        )
    return pairs


async def validate_config(paths: DoctorPaths, env: Environment | None = None) -> list[CheckResult]:
    """`tony config validate`: the checks that need neither network nor processes."""
    return await run_checks(
        paths, env or Environment(), offline=True, connect=False, check_external=False
    )
