from pathlib import Path

import pytest

from tony.core.config.secrets import SECRET_NAME, Variables, load_variables, resolve_home


def write_env(root, text):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / ".env").write_text(text)


def test_missing_env_file_is_allowed(tmp_path):
    variables = load_variables(tmp_path, environ={})

    assert variables == Variables(values={}, env_file_values={}, secret_names=frozenset())


def test_reads_values_from_env_file(tmp_path):
    write_env(tmp_path, "GITHUB_TOKEN=s3cr3t\n# comment\nOTHER='quoted value'\n")

    variables = load_variables(tmp_path, environ={})

    assert variables.values == {"GITHUB_TOKEN": "s3cr3t", "OTHER": "quoted value"}
    assert variables.env_file_values == {"GITHUB_TOKEN": "s3cr3t", "OTHER": "quoted value"}


def test_keeps_variable_name_case(tmp_path):
    write_env(tmp_path, "MixedCase=v\n")

    assert load_variables(tmp_path, environ={}).values == {"MixedCase": "v"}


def test_includes_process_environment(tmp_path):
    variables = load_variables(tmp_path, environ={"HOME": "/home/x"})

    assert variables.values == {"HOME": "/home/x"}
    assert variables.env_file_values == {}


def test_process_environment_overrides_env_file(tmp_path):
    write_env(tmp_path, "TOKEN=from-file\nONLY_FILE=f\n")

    variables = load_variables(tmp_path, environ={"TOKEN": "from-env"})

    assert variables.values == {"TOKEN": "from-env", "ONLY_FILE": "f"}
    assert variables.env_file_values == {"TOKEN": "from-file", "ONLY_FILE": "f"}


def test_every_env_file_name_is_secret(tmp_path):
    write_env(tmp_path, "GITHUB_TOKEN=s3cr3t\nNOTAS_DIR=/srv/notas\n")

    variables = load_variables(tmp_path, environ={"HOME": "/home/renzo"})

    assert variables.secret_names == {"GITHUB_TOKEN", "NOTAS_DIR"}


def test_empty_env_file_value_is_ignored(tmp_path):
    write_env(tmp_path, "NOTAS_DIR=\nGITHUB_TOKEN=s3cr3t\n")

    variables = load_variables(tmp_path, environ={})

    assert variables.env_file_values == {"GITHUB_TOKEN": "s3cr3t"}
    assert "NOTAS_DIR" not in variables.secret_names


def test_secret_looking_process_variable_is_secret(tmp_path):
    variables = load_variables(tmp_path, environ={"API_KEY": "k3y", "HOME": "/home/renzo"})

    assert variables.secret_names == {"API_KEY"}


@pytest.mark.parametrize(
    "name",
    [
        "GITHUB_TOKEN",
        "api_key",
        "Client_Secret",
        "DB_PASSWORD",
        "SMTP_PASSWD",
        "AUTHORIZATION",
        "BANK_PIN",
        "PING",
    ],
)
def test_secret_name_pattern_matches(name):
    assert SECRET_NAME.search(name)


@pytest.mark.parametrize("name", ["HOME", "PATH", "USER", "NOTAS", "LANG"])
def test_ordinary_names_do_not_match(name):
    assert not SECRET_NAME.search(name)


def test_home_from_tony_home_variable(tmp_path):
    assert resolve_home({"TONY_HOME": str(tmp_path)}) == tmp_path


def test_home_defaults_to_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_home({}) == Path.cwd()


def test_empty_tony_home_falls_back_to_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_home({"TONY_HOME": ""}) == Path.cwd()
