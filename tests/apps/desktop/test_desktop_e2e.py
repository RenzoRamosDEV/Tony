"""Offscreen end-to-end: real CoreRuntime, fake engines, one MCP server down at start."""

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.processes import processes_mentioning
from tony.apps.desktop.app import open_desktop
from tony.apps.desktop.presenters.activity import DOWN_COLOUR
from tony.core.orchestrator.runtime import CoreRuntime

NO_PIN = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def test_mcp_down_at_start_is_marked_red_and_delegation_still_works(qtbot, tmp_path):
    broken = {"broken": {"command": "/nonexistent/tony-no-such-cmd"}}
    home, notes = make_tony_home(tmp_path, policy=NO_PIN, extra_servers=broken)
    chat = FakeChatEngine(
        [CallTool("tony.delegate", {"objetivo": "Lee a.md"}), Say("Dice: comprar pan, señor.")]
    )
    worker = FakeModelEngine(
        [
            CallTool("filesystem.read_file", {"path": "a.md"}),
            Final(structured=lambda replies: {"resumen": replies[0].text}),
        ]
    )

    def factory(publish):
        return CoreRuntime(home, publish, chat_engine=chat, engine=worker, environ={})

    window, core = open_desktop(home, factory)
    qtbot.addWidget(window)
    servers = window.activity_panel.servers

    qtbot.waitUntil(lambda: servers.count() == 2, timeout=10000)
    rows = {servers.item(i).text(): servers.item(i) for i in range(servers.count())}
    [down] = [item for text, item in rows.items() if text.startswith("viernes/broken")]
    assert down.foreground().color().name().upper() == DOWN_COLOUR.upper()

    window.input.setText("Lee mi nota")
    window.input.returnPressed.emit()
    qtbot.waitUntil(lambda: "comprar pan" in window.chat_view.html, timeout=10000)

    assert worker.replies[0].text == "# Nota A\nComprar pan."
    task = window.activity_panel.tree.topLevelItem(0)
    assert task.child(0).text(0) == "filesystem.read_file — allow"
    assert window.isVisible() and core.is_alive()
    window.close()
    assert not core.is_alive()
    assert processes_mentioning(str(notes)) == []
