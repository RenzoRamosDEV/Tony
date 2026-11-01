"""Loads the real built page in Qt WebEngine offscreen (uv run pytest -m web after a build)."""

import os

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import Slot  # noqa: E402

from tests.apps.desktop.test_app import fake_factory  # noqa: E402
from tony.apps.desktop import app as desktop_app  # noqa: E402
from tony.apps.desktop.page_bridge import PageBridge  # noqa: E402
from tony.apps.desktop.page_policy import web_dist  # noqa: E402
from tony.core.events import core_events as ev  # noqa: E402

pytestmark = [
    pytest.mark.web,
    pytest.mark.skipif(not (web_dist() / "index.html").is_file(), reason="web front not built"),
]


class ReadyBridge(PageBridge):
    readies = 0

    @Slot()
    def ready(self) -> None:
        ReadyBridge.readies += 1
        super().ready()


def evaluate(qtbot, view, script):
    results = []
    view.page().runJavaScript(script, 0, results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    return results[0]


def test_the_built_page_loads_from_file_and_focuses_deny(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_app, "PageBridge", ReadyBridge)
    ReadyBridge.readies = 0
    runtimes = []
    window, core = desktop_app.open_desktop(tmp_path, fake_factory(runtimes))
    try:
        view = window.centralWidget()
        qtbot.waitUntil(lambda: ReadyBridge.readies == 1, timeout=15000)
        assert view.url().scheme() == "file"

        runtimes[0].publish(ev.voice_state("ready"))
        runtimes[0].publish(
            ev.needs_confirmation("t1", "filesystem.delete_file", "{}", "¿Autoriza?", True)
        )

        qtbot.waitUntil(
            lambda: evaluate(qtbot, view, "document.activeElement?.textContent") == "Denegar",
            timeout=5000,
        )
        assert evaluate(qtbot, view, "!!document.querySelector('.stage')") is True
        assert evaluate(qtbot, view, "document.querySelector('.stage').dataset.orbState") == (
            "confirming"
        )
    finally:
        window.close()
        shiboken6.delete(window)
    assert not core.is_alive()
