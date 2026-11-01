from typer.testing import CliRunner

from tony.apps.cli.main import create_app


def invoke(tmp_path, *args):
    launched = []
    app = create_app(desktop_launcher=lambda *, focus: launched.append(focus))
    result = CliRunner().invoke(app, list(args), env={"TONY_HOME": str(tmp_path)})
    return result, launched


def test_bare_tony_launches_the_desktop_without_help(tmp_path):
    result, launched = invoke(tmp_path)

    assert result.exit_code == 0
    assert launched == [False]
    assert "Usage" not in result.output


def test_help_still_prints_help(tmp_path):
    result, launched = invoke(tmp_path, "--help")

    assert result.exit_code == 0
    assert "Usage" in result.output and "chat" in result.output
    assert launched == []


def test_subcommand_does_not_launch(tmp_path):
    result, launched = invoke(tmp_path, "audit")

    assert result.exit_code == 0
    assert launched == []


def test_focus_launches_with_focus(tmp_path):
    result, launched = invoke(tmp_path, "--focus")

    assert result.exit_code == 0
    assert launched == [True]


def test_focus_with_a_subcommand_is_a_usage_error(tmp_path):
    result, launched = invoke(tmp_path, "--focus", "audit")

    assert result.exit_code == 2
    assert "--focus" in result.output
    assert launched == []


def test_help_lists_focus(tmp_path):
    result, _ = invoke(tmp_path, "--help")

    assert "--focus" in result.output
