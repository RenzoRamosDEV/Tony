"""Offscreen end-to-end: real CoreRuntime, fake engines, one MCP server down at start, the page
side driven through the page bridge (no Chromium)."""

import json

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.processes import processes_mentioning
from tests.fakes.web_view import FakeWebView
from tony.apps.desktop.app import open_desktop
from tony.core.orchestrator.runtime import CoreRuntime

NO_PIN = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def test_mcp_down_at_start_reaches_the_page_and_delegation_still_works(qtbot, tmp_path):
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

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    window, core = open_desktop(home, factory, view_factory=FakeWebView, dist=dist)
    qtbot.addWidget(window)
    page = []
    window.bridge.event.connect(lambda text: page.append(json.loads(text)))
    window.bridge.ready()

    def servers():
        return {(e["agent"], e["server"]): e["up"] for e in page if e["type"] == "mcp_status"}

    qtbot.waitUntil(lambda: len(servers()) == 2, timeout=10000)
    assert servers()[("viernes", "broken")] is False

    window.bridge.send(json.dumps({"type": "send_message", "text": "Lee mi nota"}))

    def reply():
        return [e for e in page if e["type"] == "result" and e["scope"] == "turn"]

    qtbot.waitUntil(lambda: bool(reply()), timeout=10000)
    assert "comprar pan" in reply()[0]["text"]
    assert worker.replies[0].text == "# Nota A\nComprar pan."
    calls = [(e["tool"], e["verdict"]) for e in page if e["type"] == "tool_call"]
    assert ("filesystem.read_file", "allow") in calls
    assert window.isVisible() and core.is_alive()
    window.close()
    assert not core.is_alive()
    assert processes_mentioning(str(notes)) == []
