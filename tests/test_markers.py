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


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def pytest_options():
    import tomllib

    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]


def test_web_and_voice_markers_are_declared():
    names = {marker.split(":")[0] for marker in pytest_options()["markers"]}
    assert {"voice", "web"} <= names


def test_web_marked_tests_are_deselected_by_default(pytester):
    import shlex

    pytester.makeini("[pytest]\nmarkers =\n    web: x\n    voice: y\n")
    pytester.makepyfile(
        """
import pytest

@pytest.mark.web
def test_page():
    pass

@pytest.mark.voice
def test_engines():
    pass

def test_plain():
    pass
"""
    )
    result = pytester.runpytest("-p", "no:asyncio", *shlex.split(pytest_options()["addopts"]))
    result.assert_outcomes(passed=1, deselected=2)
