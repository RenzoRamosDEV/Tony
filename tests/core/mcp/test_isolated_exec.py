import json
import subprocess
import sys

from tony.core.mcp import isolated_exec


def launch(command, args, env, *, launcher_env=None):
    payload = {"TONY_ISOLATED_ENV": json.dumps(env), **(launcher_env or {})}
    return subprocess.run(
        [sys.executable, "-I", isolated_exec.__file__, command, *args],
        env={"PATH": "/usr/bin:/bin", "LEAK": "1", **payload},
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_child_sees_only_the_composed_variables():
    result = launch("/usr/bin/env", [], {"ONLY": "1", "OTHER": "2"})

    assert result.returncode == 0
    assert sorted(result.stdout.splitlines()) == ["ONLY=1", "OTHER=2"]


def test_child_receives_composed_values():
    result = launch(
        sys.executable, ["-c", "import os; print(os.environ['ONLY'])"], {"ONLY": "valor"}
    )

    assert result.stdout.strip() == "valor"


def test_missing_command_exits_127_with_stderr_message():
    result = launch("no-such-command-xyz", [], {"PATH": "/usr/bin"})

    assert result.returncode == 127
    assert "no-such-command-xyz" in result.stderr


def test_command_is_looked_up_in_the_composed_path(tmp_path):
    tool = tmp_path / "mytool"
    tool.write_text("#!/bin/sh\necho found\n")
    tool.chmod(0o755)

    result = launch("mytool", [], {"PATH": str(tmp_path)})

    assert result.stdout.strip() == "found"
