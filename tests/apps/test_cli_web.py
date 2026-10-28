"""`tony web` command (specs/web-server) with the server entry point injected."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.apps.cli_helpers import write_agent
from tony.apps.cli import main

runner = CliRunner()


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch, tmp_repo: Path) -> list[Any]:
    monkeypatch.chdir(tmp_repo)
    write_agent(tmp_repo / "agents", "jarvis", "front", model="claude-haiku")
    write_agent(tmp_repo / "agents", "viernes", "worker")
    calls: list[Any] = []

    async def fake_serve(options) -> None:
        calls.append(options)

    monkeypatch.setattr(main, "web_serve", fake_serve)
    return calls


def test_remote_host_without_allow_remote_exits_2_without_serving(served) -> None:
    result = runner.invoke(main.app, ["web", "--host", "0.0.0.0"])

    assert result.exit_code == 2
    assert "--allow-remote" in result.stderr
    assert served == []


def test_remote_host_with_allow_remote_serves_and_warns(served) -> None:
    result = runner.invoke(main.app, ["web", "--host", "0.0.0.0", "--allow-remote"])

    assert result.exit_code == 0
    assert "0.0.0.0" in result.stderr
    assert len(served) == 1 and served[0].host == "0.0.0.0" and served[0].port == 8787


def test_port_and_defaults_reach_serve(served, tmp_repo: Path) -> None:
    (tmp_repo / "config" / "tony.yaml").write_text("web:\n  port: 9100\n", encoding="utf-8")

    assert runner.invoke(main.app, ["web"]).exit_code == 0
    assert runner.invoke(main.app, ["web", "--port", "9000", "--open"]).exit_code == 0

    assert (served[0].host, served[0].port, served[0].open_browser) == ("127.0.0.1", 9100, False)
    assert (served[1].port, served[1].open_browser) == (9000, True)
    assert served[1].runtime.config_path == Path("config/tony.yaml")
    assert served[1].runtime.agents_dir == Path("agents")


def test_missing_extra_exits_2_naming_the_extra(served, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "web_serve", None)

    def missing() -> Any:
        raise ImportError("No module named 'fastapi'")

    monkeypatch.setattr(main, "load_web_serve", missing)

    result = runner.invoke(main.app, ["web"])

    assert result.exit_code == 2
    assert "tony[web]" in result.stderr


def test_missing_front_exits_2_naming_it(served, monkeypatch: pytest.MonkeyPatch, tmp_repo) -> None:
    pytest.importorskip("fastapi")
    monkeypatch.setattr(main, "web_serve", None)
    (tmp_repo / "config" / "tony.yaml").write_text("front: nadie\n", encoding="utf-8")

    result = runner.invoke(main.app, ["web"])

    assert result.exit_code == 2
    assert "nadie" in result.stderr


def test_invalid_config_exits_2(served, tmp_repo: Path) -> None:
    (tmp_repo / "config" / "tony.yaml").write_text("reply_mode: loud\n", encoding="utf-8")

    result = runner.invoke(main.app, ["web"])

    assert result.exit_code == 2 and "Configuración inválida" in result.stderr


def test_web_help_is_in_spanish() -> None:
    result = runner.invoke(main.app, ["web", "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0
    for option, word in (
        ("--port", "Puerto"),
        ("--host", "escucha"),
        ("--open", "navegador"),
        ("--allow-remote", "loopback"),
        ("--config", "configuración"),
        ("--agents-dir", "agentes"),
    ):
        assert option in result.output and word in result.output


def test_open_hook_uses_webbrowser(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from tony.apps.web import server

    opened: list[str] = []
    monkeypatch.setattr(server.webbrowser, "open", lambda url: opened.append(url) or True)

    server.open_in_browser("http://127.0.0.1:8787/")

    assert opened == ["http://127.0.0.1:8787/"]
