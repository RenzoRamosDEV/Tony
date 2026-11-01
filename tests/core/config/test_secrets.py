from pathlib import Path

from tony.core.config.secrets import load_secrets, resolve_home


def write_env(root, text):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / ".env").write_text(text)


def test_missing_env_file_is_allowed(tmp_path):
    assert load_secrets(tmp_path, environ={}) == {}


def test_reads_values_from_env_file(tmp_path):
    write_env(tmp_path, "GITHUB_TOKEN=s3cr3t\n# comment\nOTHER='quoted value'\n")

    assert load_secrets(tmp_path, environ={}) == {
        "GITHUB_TOKEN": "s3cr3t",
        "OTHER": "quoted value",
    }


def test_keeps_variable_name_case(tmp_path):
    write_env(tmp_path, "MixedCase=v\n")

    assert load_secrets(tmp_path, environ={}) == {"MixedCase": "v"}


def test_includes_process_environment(tmp_path):
    assert load_secrets(tmp_path, environ={"HOME": "/home/x"}) == {"HOME": "/home/x"}


def test_process_environment_overrides_env_file(tmp_path):
    write_env(tmp_path, "TOKEN=from-file\nONLY_FILE=f\n")

    secrets = load_secrets(tmp_path, environ={"TOKEN": "from-env"})

    assert secrets == {"TOKEN": "from-env", "ONLY_FILE": "f"}


def test_home_from_tony_home_variable(tmp_path):
    assert resolve_home({"TONY_HOME": str(tmp_path)}) == tmp_path


def test_home_defaults_to_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_home({}) == Path.cwd()


def test_empty_tony_home_falls_back_to_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_home({"TONY_HOME": ""}) == Path.cwd()
