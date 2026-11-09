import importlib.util
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from tony.core.config.errors import DefinitionError
from tony.core.config.placeholders import placeholder_names
from tony.core.config.secrets import load_variables
from tony.core.config.settings import CONFIG_FILE, TonyConfig, load_config
from tony.core.guard.policy import load_policy
from tony.core.loader.agent_md import parse_agent
from tony.core.loader.tool_json import McpServer, ToolSpec, agent_folder, load_tool_spec, tool_file
from tony.core.mcp.manager import stdio_command
from tony.core.orchestrator.natives import NATIVE_TOOLS
from tony.core.voice.engines.loader import EXTRA_MISSING, REQUIRED_MODULES

Status = Literal["ok", "warn", "fail"]
Which = Callable[[str], str | None]
FindSpec = Callable[[str], ModuleSpec | None]

MUSIC_SERVER = "music"
MUSIC_BINARIES = ("yt-dlp", "mpv")
WEB_SCHEMES = ("http", "https")


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    hint: str


def run_checks(
    root: Path,
    *,
    which: Which = shutil.which,
    find_spec: FindSpec = importlib.util.find_spec,
    environ: Mapping[str, str] = os.environ,
) -> list[Check]:
    """Local installation checks; nothing is executed, imported or connected."""
    checks, config = _config_check(root)
    keys = _agent_keys(root)
    checks += [check for key in keys for check in _agent_checks(root, key, config)]
    specs = _tool_specs(root, keys)
    declared = {server for spec in specs.values() for server in spec.mcp_servers}
    variables = load_variables(root, environ).values
    for key, spec in specs.items():
        for name, server in spec.mcp_servers.items():
            checks.append(_server_check(f"{key}/{name}", server, which))
            checks.append(_placeholder_check(f"{key}/{name}", server.model_dump(), variables))
            checks += _isolation_checks(f"{key}/{name}", server, environ)
    checks.append(_voice_check(find_spec))
    if MUSIC_SERVER in declared:
        checks += [_binary_check(binary, which) for binary in MUSIC_BINARIES]
    return checks


def _definition(file: str, load: Callable[[], object]) -> Check:
    name = f"definitions:{file}"
    try:
        load()
    except DefinitionError as error:
        return Check(name, "fail", _one_line(str(error)))
    return Check(name, "ok", "loads")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _config_check(root: Path) -> tuple[list[Check], TonyConfig]:
    try:
        config = load_config(root)
    except DefinitionError as error:
        return [Check(f"definitions:{CONFIG_FILE}", "fail", _one_line(str(error)))], TonyConfig()
    return [Check(f"definitions:{CONFIG_FILE}", "ok", "loads")], config


def _agent_keys(root: Path) -> list[str]:
    agents = sorted(path.name for path in root.glob("agents/*") if path.is_dir())
    subagents = sorted(
        f"{path.parents[1].name}/{path.name}"
        for path in root.glob("agents/*/subagents/*")
        if path.is_dir()
    )
    return [*agents, *subagents]


def _agent_checks(root: Path, key: str, config: TonyConfig) -> list[Check]:
    folder = agent_folder(key)
    checks = []
    agent_file = f"{folder}agent.md"
    if (root / agent_file).is_file():
        checks.append(
            _definition(
                agent_file,
                lambda: parse_agent(
                    (root / agent_file).read_text(),
                    folder=key.rsplit("/", 1)[-1],
                    file=agent_file,
                    models=config.models,
                ),
            )
        )
    if (root / tool_file(key)).is_file():
        checks.append(
            _definition(
                tool_file(key), lambda: load_tool_spec(root, key, native_tools=NATIVE_TOOLS)
            )
        )
    if "/" not in key and (root / f"{folder}policy.yaml").is_file():
        checks.append(_definition(f"{folder}policy.yaml", lambda: load_policy(root, key)))
    return checks


def _tool_specs(root: Path, keys: list[str]) -> dict[str, ToolSpec]:
    specs = {}
    for key in keys:
        try:
            specs[key] = load_tool_spec(root, key, native_tools=NATIVE_TOOLS)
        except DefinitionError:
            continue
    return specs


def _server_check(label: str, server: McpServer, which: Which) -> Check:
    name = f"mcp:{label}"
    if server.is_stdio:
        command = server.command
        if stdio_command(command) != command or which(command):
            return Check(name, "ok", f"command {command} found")
        return Check(name, "fail", f"command {command} not found on PATH: install it")
    scheme = urlparse(server.url).scheme
    if scheme in WEB_SCHEMES:
        return Check(name, "ok", f"{scheme} url")
    return Check(name, "fail", f"url scheme must be http or https, not '{scheme}'")


def _placeholder_check(label: str, declaration: dict, variables: Mapping[str, str]) -> Check:
    name = f"vars:{label}"
    undefined = sorted(placeholder_names(declaration) - variables.keys())
    if undefined:
        return Check(name, "fail", f"undefined variables: {', '.join(undefined)}")
    return Check(name, "ok", "all placeholders defined")


def _isolation_checks(label: str, server: McpServer, environ: Mapping[str, str]) -> list[Check]:
    if server.isolation is None:
        return []
    missing = sorted(set(server.isolation.env_allow) - environ.keys())
    if not missing:
        return []
    hint = f"env_allow variables not set in the host: {', '.join(missing)}"
    return [Check(f"isolation:{label}", "warn", hint)]


def _voice_check(find_spec: FindSpec) -> Check:
    missing = [module for module in REQUIRED_MODULES if find_spec(module) is None]
    if missing:
        return Check("voice", "warn", f"missing {', '.join(missing)}: {_install_command()}")
    return Check("voice", "ok", "modules found (import not verified; PortAudio is needed)")


def _install_command() -> str:
    return EXTRA_MISSING.split(": ", 1)[1]


def _binary_check(binary: str, which: Which) -> Check:
    if which(binary):
        return Check(binary, "ok", "found on PATH")
    return Check(binary, "warn", f"{binary} not found on PATH: the music server needs it")
