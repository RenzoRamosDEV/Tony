import pytest
from typer.testing import CliRunner

from tests.core.diagnostics.test_checks import build_home
from tony.apps.cli.main import create_app
from tony.core.diagnostics.checks import Check


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def doctor(checks, tmp_path):
    app = create_app(doctor_checks=lambda root: checks)
    return CliRunner().invoke(app, ["doctor"], env={"TONY_HOME": str(tmp_path)})


def test_prints_the_table_and_exits_0_when_everything_is_ok(tmp_path):
    result = doctor([Check("definitions:x", "ok", "loads")], tmp_path)

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "check          status  hint",
        "definitions:x  ok      loads",
    ]


def test_a_failure_exits_1_and_shows_the_hint(tmp_path):
    result = doctor(
        [Check("mcp:a/b", "fail", "install npx"), Check("voice", "warn", "x")], tmp_path
    )

    assert result.exit_code == 1
    assert "install npx" in result.stdout


def test_warnings_alone_exit_0(tmp_path):
    assert doctor([Check("voice", "warn", "missing")], tmp_path).exit_code == 0


def test_default_checks_run_against_the_home(tmp_path):
    home = build_home(tmp_path)

    result = CliRunner().invoke(create_app(), ["doctor"], env={"TONY_HOME": str(home)})

    assert result.exit_code == 0
    edith = [line for line in result.stdout.splitlines() if "agents/edith/policy.yaml" in line]
    assert [cell for cell in edith[0].split()][:2] == [
        "definitions:agents/edith/policy.yaml",
        "ok",
    ]
