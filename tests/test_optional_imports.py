import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

OPTIONAL_MODULES = {
    "faster_whisper",
    "kokoro",
    "silero_vad",
    "torch",
    "sounddevice",
    "numpy",
    "desktop_notifier",
    "pynput",
}

ALLOWED = {
    *(p.relative_to(ROOT) for p in (ROOT / "tony/core/voice/engines").glob("*.py")),
    Path("tony/apps/desktop/system/notifier.py"),
    Path("tony/apps/desktop/system/hotkey.py"),
}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_engine_and_system_adapters_import_optional_extras():
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "tony").rglob("*.py")
        if path.relative_to(ROOT) not in ALLOWED and _imported_roots(path) & OPTIONAL_MODULES
    )
    assert offenders == []


def test_imported_roots_detects_lazy_imports(tmp_path):
    module = tmp_path / "m.py"
    module.write_text("def f():\n    import torch.nn\n    from numpy import zeros\n")
    assert _imported_roots(module) == {"torch", "numpy"}


@pytest.mark.parametrize("package", ["tony.core.voice.engines", "tony.apps.desktop.system"])
def test_adapter_packages_exist(package):
    assert (ROOT / package.replace(".", "/") / "__init__.py").is_file()


BLOCKER = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {names!r}:
            raise ModuleNotFoundError(name)
sys.meta_path.insert(0, Block())
import tony.core.voice, tony.core.voice.engines, tony.apps.desktop.app
"""


def test_core_voice_and_desktop_import_without_extras():
    code = BLOCKER.format(names=OPTIONAL_MODULES)
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=25
    )
    assert done.returncode == 0, done.stderr
