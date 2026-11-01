import pytest
from typer.testing import CliRunner

from tony.apps.cli.main import create_app
from tony.core.guard.pin import LOCK_FILE, PinStore


def invoke(home, *entries):
    answers = list(entries)
    prompts = []

    def getpass(prompt):
        prompts.append(prompt)
        return answers.pop(0)

    app = create_app(getpass=getpass)
    result = CliRunner().invoke(app, ["pin", "set"], env={"TONY_HOME": str(home)})
    return result, prompts


@pytest.mark.parametrize("pin", ["4821", "abcdefgh"])
def test_equal_entries_store_a_valid_lock(tmp_path, pin):
    result, prompts = invoke(tmp_path, pin, pin)

    assert result.exit_code == 0
    assert len(prompts) == 2
    assert PinStore(tmp_path).verify(pin)
    assert pin not in result.output


def test_mismatch_fails_and_keeps_the_previous_lock(tmp_path):
    PinStore(tmp_path).set("7777")
    before = (tmp_path / LOCK_FILE).read_text()

    result, _ = invoke(tmp_path, "4821", "4822")

    assert result.exit_code != 0
    assert (tmp_path / LOCK_FILE).read_text() == before
    assert "4821" not in result.output and "4822" not in result.output


def test_mismatch_without_a_previous_lock_writes_nothing(tmp_path):
    result, _ = invoke(tmp_path, "4821", "4822")

    assert result.exit_code != 0
    assert not (tmp_path / LOCK_FILE).exists()


def test_short_pin_fails_naming_the_minimum_length(tmp_path):
    result, prompts = invoke(tmp_path, "123", "123")

    assert result.exit_code != 0
    assert "at least 4 characters" in result.output
    assert not (tmp_path / LOCK_FILE).exists()
    assert "123" not in result.output


def test_pin_help(tmp_path):
    result = CliRunner().invoke(create_app(), ["pin", "--help"])

    assert result.exit_code == 0
    assert "set" in result.output
