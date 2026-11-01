import shutil
from pathlib import Path

from tests.core.orchestrator.viernes_home import REPO, make_viernes_home


def make_tony_home(tmp_path: Path, **options) -> tuple[Path, Path]:
    """A TONY_HOME with the bundled Jarvis, the fake-server Viernes and the bundled Edith."""
    home, notes = make_viernes_home(tmp_path, **options)
    shutil.copytree(REPO / "agents" / "jarvis", home / "agents" / "jarvis")
    return home, notes


def set_config(home: Path, text: str) -> None:
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / "tony.yaml").write_text(text)
