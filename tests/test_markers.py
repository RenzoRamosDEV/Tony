from pathlib import Path

import pytest

CONFTEST = Path(__file__).with_name("conftest.py")

EVALS_TEST = """
import pytest

@pytest.mark.evals
def test_real_model():
    pass
"""


@pytest.fixture
def evals_project(pytester):
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile(EVALS_TEST)
    return pytester


def test_evals_test_is_skipped_without_variable(evals_project, monkeypatch):
    monkeypatch.delenv("TONY_EVALS", raising=False)
    evals_project.runpytest("-p", "no:asyncio").assert_outcomes(skipped=1)


@pytest.mark.parametrize("value", ["0", "", "true"])
def test_evals_test_is_skipped_unless_variable_is_one(evals_project, monkeypatch, value):
    monkeypatch.setenv("TONY_EVALS", value)
    evals_project.runpytest("-p", "no:asyncio").assert_outcomes(skipped=1)


def test_evals_test_runs_with_variable(evals_project, monkeypatch):
    monkeypatch.setenv("TONY_EVALS", "1")
    evals_project.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)
