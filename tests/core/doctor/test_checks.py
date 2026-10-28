"""Doctor checks with injected dependencies (specs/cli-doctor)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.apps.cli_helpers import write_agent
from tests.core.runner_helpers import mcp_tool
from tony.core.doctor.checks import CheckResult, DoctorPaths, Environment, exit_code, run_checks
from tony.core.mcp import McpServerStatus, ToolCatalog

FAKE = {"command": "python", "args": ["-m", "tests.fakes.fake_mcp_server"]}


def paths(tmp_repo: Path) -> DoctorPaths:
    return DoctorPaths(
        config_path=tmp_repo / "config" / "tony.yaml", agents_dir=tmp_repo / "agents"
    )


def healthy_repo(tmp_repo: Path, tool_json: dict | None = None) -> DoctorPaths:
    (tmp_repo / "config" / "tony.yaml").write_text("worker: viernes\n", encoding="utf-8")
    env = tmp_repo / "config" / ".env"
    env.write_text("", encoding="utf-8")
    env.chmod(0o600)
    write_agent(tmp_repo / "agents", "viernes", "worker")
    write_agent(tmp_repo / "agents", "jarvis", "front", model="claude-haiku")
    tool = tmp_repo / "agents" / "viernes" / "tool"
    tool.mkdir(exist_ok=True)
    (tool / "tool.json").write_text(
        json.dumps(tool_json or {"mcpServers": {"fake": FAKE}, "confirm": ["fake.destroy"]}),
        encoding="utf-8",
    )
    return paths(tmp_repo)


class Probe:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def __call__(self, settings) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("Not logged in")
        return "OK"


class Connector:
    def __init__(self, tools: list[str] | None = None, down: list[str] | None = None) -> None:
        self.tools = tools if tools is not None else ["echo", "fail", "slow", "destroy"]
        self.down = down or []
        self.calls: list[Any] = []

    async def __call__(
        self, settings, tool_config
    ) -> tuple[dict[str, McpServerStatus], ToolCatalog]:
        self.calls.append(tool_config)
        statuses = {}
        tools_by_server = {}
        for name in tool_config.mcpServers:
            if name in self.down:
                statuses[name] = McpServerStatus(name, "error", "no se pudo arrancar", 0, None)
            else:
                statuses[name] = McpServerStatus(name, "ready", None, len(self.tools), None)
                tools_by_server[name] = [mcp_tool(t) for t in self.tools]
        return statuses, ToolCatalog.build(tools_by_server, None, [])


def environment(
    which: Callable[[str], str | None] = lambda name: f"/usr/bin/{name}",
    python_version: tuple[int, int] = (3, 12),
    find_spec: Callable[[str], Any] = lambda name: None,
    probe: Probe | None = None,
    connector: Connector | None = None,
) -> Environment:
    return Environment(
        which=which,
        python_version=python_version,
        find_spec=find_spec,
        probe_model=probe or Probe(),
        connect_mcp=connector or Connector(),
    )


async def check(
    tmp_repo: Path, env: Environment | None = None, **options
) -> dict[str, CheckResult]:
    results = await run_checks(
        options.pop("paths", None) or healthy_repo(tmp_repo),
        env or environment(),
        offline=options.get("offline", True),
        connect=options.get("connect", True),
    )
    return {r.name: r for r in results}


def failed(results: dict[str, CheckResult]) -> list[str]:
    return [name for name, r in results.items() if r.failed]


async def test_healthy_installation_only_omits_the_model(tmp_repo: Path) -> None:
    results = await check(tmp_repo)

    assert failed(results) == []
    assert results["modelo"].ok is None and "offline" in results["modelo"].detail
    assert results["python"].ok is True
    assert results["claude"].ok is True
    assert results["config/tony.yaml"].ok is True
    assert results["config/.env"].ok is True
    assert results["agente viernes"].ok is True
    assert (
        results["mcp viernes/fake"].ok is True and "4 tools" in results["mcp viernes/fake"].detail
    )
    assert exit_code(results.values()) == 0


@pytest.mark.parametrize("version,ok", [((3, 11), False), ((3, 12), True), ((3, 13), False)])
async def test_python_version_must_be_3_12(tmp_repo: Path, version, ok) -> None:
    results = await check(tmp_repo, environment(python_version=version))

    assert results["python"].ok is ok
    if not ok:
        assert "3.12" in results["python"].hint


async def test_missing_claude_cli_suggests_installing_and_authenticating(tmp_repo: Path) -> None:
    results = await check(tmp_repo, environment(which=lambda n: None if n == "claude" else "/x"))

    assert results["claude"].ok is False
    assert "claude" in results["claude"].detail
    assert "Claude Code" in results["claude"].hint and "login" in results["claude"].hint


async def test_model_probe_failure_is_reported_and_skipped_offline(tmp_repo: Path) -> None:
    probe = Probe(fail=True)

    online = await check(tmp_repo, environment(probe=probe), offline=False)
    offline = await check(tmp_repo, environment(probe=probe), offline=True)

    assert online["modelo"].ok is False and "Not logged in" in online["modelo"].detail
    assert "claude login" in online["modelo"].hint
    assert offline["modelo"].ok is None
    assert probe.calls == 1


async def test_model_probe_success_shows_the_reply(tmp_repo: Path) -> None:
    results = await check(tmp_repo, environment(probe=Probe()), offline=False)

    assert results["modelo"].ok is True and "OK" in results["modelo"].detail


async def test_invalid_tony_yaml_names_the_field(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    p.config_path.write_text("reply_mode: loud\n", encoding="utf-8")

    results = await check(tmp_repo, paths=p)

    assert results["config/tony.yaml"].ok is False
    assert "reply_mode" in results["config/tony.yaml"].detail
    assert "config/tony.yaml" in results["config/tony.yaml"].hint
    assert results["agente viernes"].ok is True


async def test_missing_env_file_suggests_creating_it_with_600(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    (tmp_repo / "config" / ".env").unlink()

    results = await check(tmp_repo, paths=p)

    assert results["config/.env"].ok is False
    assert "config/.env" in results["config/.env"].detail
    assert "600" in results["config/.env"].hint


@pytest.mark.parametrize("mode,ok", [(0o644, False), (0o640, False), (0o600, True), (0o400, True)])
async def test_env_permissions(tmp_repo: Path, mode: int, ok: bool) -> None:
    p = healthy_repo(tmp_repo)
    (tmp_repo / "config" / ".env").chmod(mode)

    results = await check(tmp_repo, paths=p)

    assert results["config/.env"].ok is ok
    if not ok:
        assert results["config/.env"].hint == "chmod 600 config/.env"
        assert oct(mode)[-3:] in results["config/.env"].detail


async def test_broken_agent_invalid_skill_and_missing_variable_are_reported(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo, {"mcpServers": {"n": {"url": "${NOTION_URL}"}}})
    write_agent(tmp_repo / "agents", "roto", "helper")
    skill = tmp_repo / "agents" / "jarvis" / "skills" / "mala" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: mala\n---\n", encoding="utf-8")

    results = await check(tmp_repo, paths=p, connect=False)

    assert "role" in results["agente roto"].detail and results["agente roto"].ok is False
    assert (
        results["skill jarvis/mala"].ok is False
        and "description" in results["skill jarvis/mala"].detail
    )
    viernes = results["agente viernes"]
    assert viernes.ok is False and "NOTION_URL" in viernes.detail
    assert "config/.env" in viernes.hint


async def test_npx_is_required_only_when_an_mcp_uses_it(tmp_repo: Path) -> None:
    no_node = environment(which=lambda n: None if n in ("npx", "node") else "/x")

    unused = await check(tmp_repo, no_node)
    p = healthy_repo(tmp_repo, {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "x"]}}})
    used = await check(tmp_repo, no_node, paths=p, connect=False)

    assert unused["node/npx"].ok is None
    assert used["node/npx"].ok is False
    assert "npx" in used["node/npx"].detail and "Node.js" in used["node/npx"].hint


async def test_voice_extras_and_espeak_are_informative(tmp_repo: Path) -> None:
    missing = await check(tmp_repo, environment(which=lambda n: None if n == "espeak-ng" else "/x"))
    present = await check(
        tmp_repo, environment(find_spec=lambda name: object(), which=lambda n: f"/usr/bin/{n}")
    )

    assert missing["voice"].ok is None and "voice" in missing["voice"].detail
    assert missing["espeak-ng"].ok is None and missing["espeak-ng"].failed is False
    assert present["voice"].ok is None and "instalad" in present["voice"].detail
    assert present["espeak-ng"].ok is True
    assert exit_code(missing.values()) == 0


async def test_mcp_connection_results_and_patterns(tmp_repo: Path) -> None:
    p = healthy_repo(
        tmp_repo,
        {
            "mcpServers": {"fake": FAKE, "broken": {"command": "/no/existe"}},
            "allow": ["fake.nada", "fake.*"],
            "confirm": ["fake.destroy", "broken.x"],
        },
    )
    connector = Connector(down=["broken"])

    results = await check(tmp_repo, environment(connector=connector), paths=p)

    assert results["mcp viernes/fake"].ok is True
    assert results["mcp viernes/broken"].ok is False
    assert "no se pudo arrancar" in results["mcp viernes/broken"].detail
    assert results["patrón viernes/fake.nada"].ok is False
    assert "allow" in results["patrón viernes/fake.nada"].hint
    assert "patrón viernes/fake.*" not in results
    assert "patrón viernes/broken.x" not in results
    assert connector.calls[0].allow is None and connector.calls[0].confirm == []


async def test_subagent_servers_are_connected_too(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    child = tmp_repo / "agents" / "viernes" / "subagents" / "investigador"
    write_agent(tmp_repo / "agents" / "viernes" / "subagents", "investigador", "worker")
    (child / "tool").mkdir()
    (child / "tool" / "tool.json").write_text(
        json.dumps({"mcpServers": {"fetch": FAKE}}), encoding="utf-8"
    )

    results = await check(tmp_repo, paths=p)

    assert results["mcp viernes/investigador/fetch"].ok is True


async def test_without_connect_no_mcp_is_contacted(tmp_repo: Path) -> None:
    connector = Connector()

    results = await check(tmp_repo, environment(connector=connector), connect=False)

    assert connector.calls == []
    assert not any(name.startswith("mcp ") for name in results)


def test_exit_code_is_1_only_with_a_failure() -> None:
    assert exit_code([CheckResult("a", True), CheckResult("b", None)]) == 0
    assert exit_code([CheckResult("a", True), CheckResult("b", False)]) == 1
    assert exit_code([]) == 0


async def test_missing_agents_dir_is_a_failure(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    p = DoctorPaths(p.config_path, tmp_repo / "nadie")

    results = await check(tmp_repo, paths=p)

    assert results["agents"].ok is False and "nadie" in results["agents"].detail


# --- exact results ------------------------------------------------------------------------------

HEALTHY_ORDER = [
    "python",
    "claude",
    "config/tony.yaml",
    "modelo",
    "config/.env",
    "agente jarvis",
    "agente viernes",
    "node/npx",
    "voice",
    "espeak-ng",
    "mcp viernes/fake",
]


async def test_healthy_results_are_exact_and_ordered(tmp_repo: Path) -> None:
    results = await check(tmp_repo)

    assert list(results) == HEALTHY_ORDER
    assert results["python"] == CheckResult("python", True, "3.12")
    assert results["claude"] == CheckResult("claude", True, "/usr/bin/claude")
    assert results["config/tony.yaml"] == CheckResult(
        "config/tony.yaml", True, "front jarvis, worker viernes"
    )
    assert results["modelo"] == CheckResult("modelo", None, "omitido (--offline)")
    assert results["config/.env"] == CheckResult("config/.env", True, "permisos 600")
    assert results["agente viernes"] == CheckResult("agente viernes", True, "worker, claude-sonnet")
    assert results["node/npx"] == CheckResult("node/npx", None, "ningún MCP usa node/npx; omitido")
    assert results["voice"] == CheckResult(
        "voice", None, "extras de voz no instalados (tony[voice])"
    )
    assert results["espeak-ng"] == CheckResult("espeak-ng", True, "/usr/bin/espeak-ng")
    assert results["mcp viernes/fake"] == CheckResult("mcp viernes/fake", True, "4 tools")


async def test_failure_results_are_exact(tmp_repo: Path) -> None:
    p = healthy_repo(
        tmp_repo,
        {
            "mcpServers": {"fs": {"command": "npx", "args": ["-y", "x"]}, "broken": FAKE},
            "allow": ["fs.nada"],
        },
    )
    (tmp_repo / "config" / ".env").chmod(0o644)
    p = DoctorPaths(p.config_path, p.agents_dir)
    env = environment(
        which=lambda n: None if n in ("claude", "node", "npx", "espeak-ng") else f"/usr/bin/{n}",
        python_version=(3, 11),
        find_spec=lambda name: object(),
        probe=Probe(fail=True),
        connector=Connector(down=["broken"]),
    )

    results = await check(tmp_repo, env, paths=p, offline=False)

    assert results["python"] == CheckResult(
        "python", False, "versión 3.11", "usa Python 3.12 (por ejemplo: uv python install 3.12)"
    )
    assert results["claude"] == CheckResult(
        "claude",
        False,
        "el CLI 'claude' no está en el PATH",
        "instala Claude Code CLI y autentícalo con `claude login`",
    )
    assert results["modelo"] == CheckResult(
        "modelo",
        False,
        "claude-haiku no respondió: Not logged in",
        "autentica Claude Code CLI con `claude login` y revisa la red",
    )
    assert results["config/.env"] == CheckResult(
        "config/.env", False, "permisos 644 (legible por otros)", "chmod 600 config/.env"
    )
    assert results["node/npx"] == CheckResult(
        "node/npx",
        False,
        "faltan node, npx en el PATH; los usan viernes/fs",
        "instala Node.js (incluye npx), por ejemplo con nvm",
    )
    assert results["voice"] == CheckResult("voice", None, "extras de voz instalados")
    assert results["espeak-ng"] == CheckResult(
        "espeak-ng", None, "no encontrado (solo necesario para la voz)"
    )
    assert results["mcp viernes/broken"] == CheckResult(
        "mcp viernes/broken",
        False,
        "no se pudo arrancar",
        "revisa command/url del servidor 'broken' en tool.json",
    )
    assert results["patrón viernes/fs.nada"] == CheckResult(
        "patrón viernes/fs.nada",
        False,
        "no coincide con ninguna tool del servidor",
        "revisa allow/confirm en tool.json",
    )


async def test_model_success_and_node_presence_are_exact(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo, {"mcpServers": {"fs": {"command": "node", "args": ["x"]}}})

    results = await check(
        tmp_repo, environment(probe=Probe()), paths=p, offline=False, connect=False
    )

    assert results["modelo"] == CheckResult("modelo", True, "claude-haiku respondió: OK")
    assert results["node/npx"] == CheckResult("node/npx", True, "disponibles; los usan viernes/fs")


async def test_missing_env_and_agents_dir_are_exact(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    (tmp_repo / "config" / ".env").unlink()
    missing = DoctorPaths(p.config_path, tmp_repo / "nadie")

    results = await check(tmp_repo, paths=missing)

    assert results["config/.env"] == CheckResult(
        "config/.env",
        False,
        f"no existe {tmp_repo / 'config' / '.env'}",
        "créalo con permisos 600: touch config/.env && chmod 600 config/.env",
    )
    assert results["agents"] == CheckResult(
        "agents",
        False,
        f"no existe el directorio {tmp_repo / 'nadie'}",
        "crea agents/ con un agente por carpeta",
    )
    assert not any(name.startswith("agente ") for name in results)


async def test_invalid_settings_result_is_exact_and_defaults_are_used(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    p.config_path.write_text("reply_mode: loud\n", encoding="utf-8")

    results = await check(tmp_repo, paths=p)

    result = results["config/tony.yaml"]
    assert result.ok is False and result.detail.startswith("reply_mode: ")
    assert result.hint == "corrige el campo indicado en config/tony.yaml"
    assert results["agente viernes"].ok is True


async def test_validate_config_equals_offline_checks_without_connection(tmp_repo: Path) -> None:
    from tony.core.doctor.checks import validate_config

    env = environment(connector=Connector())
    p = healthy_repo(tmp_repo)

    validated = await validate_config(p, env)
    offline = await run_checks(p, env, offline=True, connect=False)

    assert validated == offline
    assert env.connect_mcp.calls == []
    assert [r.name for r in validated] == HEALTHY_ORDER[:-1]


async def test_subagent_results_name_the_parent_path(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    write_agent(tmp_repo / "agents" / "viernes" / "subagents", "investigador", "worker")
    skill = (
        tmp_repo / "agents" / "viernes" / "subagents" / "investigador" / "skills" / "s" / "SKILL.md"
    )
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: s\ndescription: d\n---\n", encoding="utf-8")

    results = await check(tmp_repo, paths=p, connect=False)

    assert results["subagente viernes/investigador"] == CheckResult(
        "subagente viernes/investigador", True, "claude-sonnet"
    )
    assert results["skill viernes/subagents/investigador/s"] == CheckResult(
        "skill viernes/subagents/investigador/s", True, "d"
    )


async def test_configured_front_and_worker_must_exist_as_folders(tmp_repo: Path) -> None:
    p = healthy_repo(tmp_repo)
    import shutil

    shutil.rmtree(tmp_repo / "agents" / "jarvis")
    shutil.rmtree(tmp_repo / "agents" / "viernes")

    results = await check(tmp_repo, paths=p, connect=False)

    assert failed(results) == ["agente jarvis", "agente viernes"]
    assert results["agente jarvis"] == CheckResult(
        "agente jarvis",
        False,
        f"no existe la carpeta {tmp_repo / 'agents' / 'jarvis'}",
        "crea agents/jarvis/agent.md o cambia front/worker en config/tony.yaml",
    )
    assert results["agente viernes"].failed
    assert list(results)[5:7] == ["agente jarvis", "agente viernes"]
