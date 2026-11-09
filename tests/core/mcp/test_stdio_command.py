import sys

import pytest

from tony.core.mcp.manager import stdio_command


@pytest.mark.parametrize("declared", ["python", "python3"])
def test_bare_python_runs_with_the_interpreter_of_tony(declared):
    assert stdio_command(declared) == sys.executable


@pytest.mark.parametrize("declared", ["npx", "/usr/bin/python3", "python3.12", "uvx"])
def test_any_other_command_is_left_untouched(declared):
    assert stdio_command(declared) == declared
