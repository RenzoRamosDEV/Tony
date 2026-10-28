"""`tony replay` prints a log readably and converts it into an eval (specs/evals)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.core.logging.test_replay import EVENTS, write_log
from tony.apps.cli import main

runner = CliRunner()


@pytest.fixture
def log(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_repo)
    return write_log(tmp_repo / "logs" / "t1.jsonl")


def test_replay_prints_the_sequence(log: Path) -> None:
    result = runner.invoke(main.app, ["replay", str(log)])

    assert result.exit_code == 0, result.output
    for text in ("fake.echo", "hola", "3 ms", "10/5", "0.01", "status: ok", "Hecho"):
        assert text in result.stdout


def test_invalid_file_exits_1_naming_the_line(log: Path) -> None:
    log.write_text('{"type": "a"}\nno json\n', encoding="utf-8")

    result = runner.invoke(main.app, ["replay", str(log)])

    assert result.exit_code == 1
    assert "línea 2" in result.stderr


def test_missing_file_exits_1(log: Path) -> None:
    result = runner.invoke(main.app, ["replay", "logs/nadie.jsonl"])

    assert result.exit_code == 1 and "nadie.jsonl" in result.stderr


def test_to_eval_writes_the_fixture_and_prints_the_entry(log: Path) -> None:
    result = runner.invoke(main.app, ["replay", str(log), "--to-eval", "fs-list-md"])

    assert result.exit_code == 0, result.output
    fixture = Path("evals/fixtures/fs-list-md.jsonl")
    assert fixture.exists()
    assert [json.loads(line)["type"] for line in fixture.read_text().splitlines()] == [
        t for t, _ in EVENTS
    ]
    for text in ("id: fs-list-md", "agent: viernes", "status: ok", "filesystem.list_directory"):
        assert text in result.stdout


def test_existing_fixture_is_kept_unless_forced(log: Path) -> None:
    fixture = Path("evals/fixtures/fs-list-md.jsonl")
    fixture.parent.mkdir(parents=True)
    fixture.write_text("previo\n", encoding="utf-8")

    result = runner.invoke(main.app, ["replay", str(log), "--to-eval", "fs-list-md"])
    assert result.exit_code == 1
    assert "fs-list-md.jsonl" in result.stderr and "--force" in result.stderr
    assert fixture.read_text() == "previo\n"

    forced = runner.invoke(main.app, ["replay", str(log), "--to-eval", "fs-list-md", "--force"])
    assert forced.exit_code == 0
    assert fixture.read_text() != "previo\n"


def test_fixtures_dir_option_and_help(log: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        main.app, ["replay", str(log), "--to-eval", "x", "--fixtures-dir", str(tmp_path / "f")]
    )

    assert result.exit_code == 0 and (tmp_path / "f" / "x.jsonl").exists()
    help_text = runner.invoke(main.app, ["replay", "--help"]).stdout
    assert "--to-eval" in help_text and "--force" in help_text and "eventos" in help_text
    assert "replay" in runner.invoke(main.app, ["--help"]).stdout


def test_to_eval_reports_the_fixture_on_stderr(log: Path) -> None:
    result = runner.invoke(main.app, ["replay", str(log), "--to-eval", "fs-list-md"])

    assert result.stderr.strip().splitlines()[-1] == (
        "# fixture: evals/fixtures/fs-list-md.jsonl (8 eventos)"
    )


def test_to_eval_warns_on_stderr_about_an_incomplete_request(log: Path) -> None:
    result = runner.invoke(main.app, ["replay", str(log), "--to-eval", "fs-list-md"])

    assert result.exit_code == 0, result.output
    assert "petición incompleta en el registro" in result.stderr
    assert "contexto: ''" in result.stdout
