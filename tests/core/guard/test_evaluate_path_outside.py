import pytest

from tony.core.guard.evaluate import Verdict, evaluate
from tony.core.guard.policy import Policy

HOME = "/home/tester"
POLICY = Policy.model_validate(
    {
        "default": "allow",
        "rules": [
            {
                "match": "fs.*",
                "verdict": "confirm",
                "when": {"path_outside": ["~/notas", "~/proyectos/"]},
            }
        ],
    }
)
OUTSIDE = Verdict("confirm", "fs.*/confirm")
INSIDE = Verdict("allow", "default")


@pytest.fixture(autouse=True)
def fake_home(monkeypatch):
    monkeypatch.setenv("HOME", HOME)


@pytest.mark.parametrize(
    "path",
    [
        "~/notas/a.md",
        "~/notas",
        "~/notas/",
        f"{HOME}/notas/sub/b.md",
        "~/proyectos/x/y.py",
        "~/proyectos",
        "~/notas/./a.md",
        "~/proyectos/../notas/a.md",
    ],
)
def test_path_inside_an_allowed_folder_does_not_hold(path):
    assert evaluate(POLICY, "fs.write", {"path": path}) == INSIDE


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/a.md",
        "~/notas/../secretos/x.md",
        "~/notasx/a.md",
        "~/nota",
        "~",
        "/",
        f"{HOME}/proyectosx",
    ],
)
def test_path_outside_every_allowed_folder_holds(path):
    assert evaluate(POLICY, "fs.write", {"path": path}) == OUTSIDE


def test_relative_path_is_normalised_against_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert evaluate(POLICY, "fs.write", {"path": "notas/a.md"}) == OUTSIDE


@pytest.mark.parametrize("key", ["path", "source", "destination"])
def test_each_path_key_is_checked(key):
    args = {"path": "~/notas/a.md", key: "/etc/passwd"}

    assert evaluate(POLICY, "fs.move", args) == OUTSIDE


def test_one_of_several_paths_outside_holds():
    args = {"paths": ["~/notas/a.md", "/etc/passwd"]}

    assert evaluate(POLICY, "fs.read_multiple", args) == OUTSIDE


def test_all_paths_inside_does_not_hold():
    args = {"source": "~/notas/a.md", "destination": "~/proyectos/a.md", "paths": ["~/notas"]}

    assert evaluate(POLICY, "fs.move", args) == INSIDE


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"content": "/etc/passwd"},
        {"path": 7},
        {"path": None},
        {"path": ["/etc/passwd"]},
        {"paths": "/etc/passwd"},
        {"paths": [1, None]},
        {"nested": {"path": "/etc/passwd"}},
    ],
)
def test_no_string_path_value_does_not_hold(args):
    assert evaluate(POLICY, "fs.write", args) == INSIDE
