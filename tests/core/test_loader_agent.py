"""Tests for agent.md loading (specs/agent-loader)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tony.core.config import load_settings
from tony.core.loader import AgentLoadError, load_agent

JARVIS_MD = """---
name: jarvis
role: front
model: claude-haiku
persona:
  address: señor
  language: es
style:
  voice: "Frases cortas, sin markdown, números redondeados."
  text: "Markdown, detalle completo, tablas si ayudan."
max_steps: 20
---
Eres Jarvis, el asistente personal de Renzo...
"""


@pytest.fixture
def settings():
    return load_settings(None)


def make_agent(agents_dir: Path, name: str, agent_md: str) -> Path:
    folder = agents_dir / name
    folder.mkdir(parents=True)
    (folder / "agent.md").write_text(agent_md, encoding="utf-8")
    return folder


def test_full_agent_is_loaded(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo / "agents", "jarvis", JARVIS_MD)

    spec = load_agent(folder, settings, {})

    assert spec.name == "jarvis"
    assert spec.role == "front"
    assert spec.model == "claude-haiku"
    assert spec.persona.address == "señor"
    assert spec.persona.language == "es"
    assert spec.style.voice == "Frases cortas, sin markdown, números redondeados."
    assert spec.style.text == "Markdown, detalle completo, tablas si ayudan."
    assert spec.max_steps == 20
    assert spec.system_prompt == "Eres Jarvis, el asistente personal de Renzo..."
    assert spec.path == folder


def test_optional_fields_take_defaults(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "min",
        "---\nname: min\nrole: worker\nmodel: claude-sonnet\n---\nHola\n",
    )

    spec = load_agent(folder, settings, {})

    assert spec.persona.language == "es"
    assert spec.persona.address == ""
    assert spec.style.voice == ""
    assert spec.style.text == ""
    assert spec.max_steps == 20
    assert spec.wait_phrase == "Dame un momento."
    assert spec.tools.mcpServers == {}


@pytest.mark.parametrize("max_steps", [0, 201, 500])
def test_max_steps_out_of_range_names_field_and_range(tmp_repo: Path, settings, max_steps) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        f"---\nname: x\nrole: worker\nmodel: claude-sonnet\nmax_steps: {max_steps}\n---\nHola\n",
    )

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "max_steps" in message
    assert "1..200" in message
    assert exc_info.value.agent == "x"


@pytest.mark.parametrize("max_steps", [1, 200])
def test_max_steps_boundaries_are_accepted(tmp_repo: Path, settings, max_steps) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        f"---\nname: x\nrole: worker\nmodel: claude-sonnet\nmax_steps: {max_steps}\n---\nHola\n",
    )

    assert load_agent(folder, settings, {}).max_steps == max_steps


def test_invalid_role_names_field_and_allowed_values(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents", "x", "---\nname: x\nrole: helper\nmodel: claude-sonnet\n---\nHola\n"
    )

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "role" in message and "front" in message and "worker" in message


def test_missing_frontmatter_is_reported(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo / "agents", "x", "Eres un agente sin frontmatter.\n")

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert "frontmatter" in str(exc_info.value)


def test_effort_field_is_loaded(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        "---\nname: x\nrole: worker\nmodel: claude-haiku\neffort: medium\n---\nHola\n",
    )

    spec = load_agent(folder, settings, {})

    assert spec.effort == "medium"


def test_effort_defaults_to_none(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        "---\nname: x\nrole: worker\nmodel: claude-sonnet\n---\nHola\n",
    )

    spec = load_agent(folder, settings, {})

    assert spec.effort is None


def test_invalid_effort_names_field_and_allowed_values(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        "---\nname: x\nrole: worker\nmodel: claude-sonnet\neffort: turbo\n---\nHola\n",
    )

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "effort" in message
    assert "medium" in message


def test_unknown_model_alias_lists_available(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents", "x", "---\nname: x\nrole: worker\nmodel: claude-ultra\n---\nHola\n"
    )

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "claude-ultra" in message
    assert "claude-haiku" in message and "claude-sonnet" in message


def test_missing_agent_md_is_reported(tmp_repo: Path, settings) -> None:
    folder = tmp_repo / "agents" / "ghost"
    folder.mkdir()

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert "agent.md" in str(exc_info.value)


@pytest.mark.parametrize(
    ("agent_md", "fragment"),
    [
        ("sin frontmatter", "frontmatter"),
        ("---\nname: x\nrole: worker\nmodel: claude-ultra\n---\nHola\n", "claude-ultra"),
        ("---\nname: x\nrole: helper\nmodel: claude-sonnet\n---\nHola\n", "role"),
    ],
)
def test_every_failure_carries_agent_name_and_message(tmp_repo, settings, agent_md, fragment):
    folder = make_agent(tmp_repo / "agents", "x", agent_md)

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert exc_info.value.agent == "x"
    assert fragment in exc_info.value.message
    assert str(exc_info.value).startswith("x: ")
    assert "Value error" not in str(exc_info.value)


def test_engine_defaults_to_claude_sdk_when_absent(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents", "x", "---\nname: x\nrole: worker\nmodel: claude-sonnet\n---\nHola\n"
    )

    spec = load_agent(folder, settings, {})

    assert spec.engine == "claude_sdk"


def test_engine_declared_and_valid_is_kept(tmp_repo: Path) -> None:
    from tony.core.config.settings import EngineProfile, TonySettings

    settings = TonySettings(
        engines={"openai_gpt": EngineProfile(type="litellm", model="openai/gpt-4o")}
    )
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        "---\nname: x\nrole: worker\nmodel: claude-sonnet\nengine: openai_gpt\n---\nHola\n",
    )

    spec = load_agent(folder, settings, {})

    assert spec.engine == "openai_gpt"


def test_unknown_engine_profile_lists_available(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        "---\nname: x\nrole: worker\nmodel: claude-sonnet\nengine: no_declarado\n---\nHola\n",
    )

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "no_declarado" in message
    assert "claude_sdk" in message
    assert exc_info.value.agent == "x"


@pytest.mark.parametrize("key", ["path", "system_prompt", "tools", "secrets"])
def test_reserved_frontmatter_keys_are_rejected(tmp_repo: Path, settings, key: str) -> None:
    folder = make_agent(
        tmp_repo / "agents",
        "x",
        f"---\nname: x\nrole: worker\nmodel: claude-sonnet\n{key}: 1\n---\n",
    )

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert exc_info.value.agent == "x"
    assert key in exc_info.value.message
