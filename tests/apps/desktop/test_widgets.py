import json
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit

from tony.apps.desktop.presenters.activity import DOWN_COLOUR
from tony.apps.desktop.widgets.main_window import MainWindow, Presenters
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling
from tony.core.guard.audit import AUDIT_FILE

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def window(qtbot, tmp_path):
    sent = []
    clock = Clock()
    presenters = Presenters.create(sent.append, tmp_path, now=lambda: NOW, monotonic=clock)
    main = MainWindow(presenters)
    qtbot.addWidget(main)
    main.show()
    main.sent, main.clock = sent, clock
    return main


def test_window_has_chat_and_collapsible_activity_and_edith_zones(window):
    assert window.chat_view.isVisible()
    for zone in (window.activity_zone, window.edith_zone):
        assert zone.isCheckable() and zone.isChecked()


def test_collapsing_a_zone_keeps_its_content(window):
    window.dispatch(ev.task_started("t1", "viernes", "Lista"))

    window.activity_zone.setChecked(False)

    assert not window.activity_panel.isVisible()
    assert window.activity_panel.tree.topLevelItemCount() == 1
    window.activity_zone.setChecked(True)
    assert window.activity_panel.isVisible()


def test_enter_sends_the_message_and_clears_the_input(window, qtbot):
    qtbot.keyClicks(window.input, "Hola")
    qtbot.keyClick(window.input, Qt.Key.Key_Return)

    assert window.sent == [{"type": "send_message", "text": "Hola"}]
    assert window.input.text() == ""


def test_mode_selector(window):
    items = [window.mode_selector.itemText(i) for i in range(window.mode_selector.count())]
    assert items == ["auto", "voice", "text", "both"]

    window.mode_selector.setCurrentText("text")
    assert window.sent == [{"type": "set_mode", "mode": "text"}]


def test_mode_selector_follows_reply_mode_events_without_sending(window):
    window.dispatch(ev.reply_mode("both"))

    assert window.mode_selector.currentText() == "both"
    assert window.sent == []


def test_microphone_placeholder(window):
    assert window.microphone.isVisible()
    assert not window.microphone.isEnabled()
    assert "voz" in window.microphone.toolTip().lower()


def test_streamed_tokens_render_one_bubble(window):
    window.dispatch(ev.token("jarvis", "Buenas"))
    window.dispatch(ev.token("jarvis", " **tardes**"))

    html = window.chat_view.html
    assert window.chat_view.bubble_count == 1
    assert "<strong>tardes</strong>" in html
    assert "#2F6FED" in html and "Jarvis" in html


def test_activity_marks_a_down_server_red(window):
    window.dispatch(ev.mcp_status("viernes", "broken", up=False, reason="no such command"))
    window.dispatch(ev.mcp_status("viernes", "filesystem", up=True, reason=None))

    servers = window.activity_panel.servers
    down, up = servers.item(0), servers.item(1)
    assert down.text() == "viernes/broken — caído: no such command"
    assert down.foreground().color().name().upper() == DOWN_COLOUR.upper()
    assert up.foreground().color().name().upper() != DOWN_COLOUR.upper()


def test_activity_tree_shows_tool_calls_under_the_task(window):
    window.dispatch(ev.task_started("t1", "viernes", "Lista"))
    window.dispatch(
        ev.tool_call(
            "t1", "viernes", "filesystem.read_file", "{}", Ruling(verdict="allow", rule="r")
        )
    )

    task = window.activity_panel.tree.topLevelItem(0)
    assert task.text(0) == "viernes: Lista"
    assert task.child(0).text(0) == "filesystem.read_file — allow"


def confirm_event(tool="filesystem.delete_file", allow_always=True):
    return ev.needs_confirmation("t1", tool, "{}", "¿Autoriza?", allow_always)


@pytest.mark.parametrize(
    ("button", "decision"),
    [("allow_button", "allow"), ("deny_button", "deny"), ("always_button", "always")],
)
def test_banner_buttons_send_the_three_commands(window, qtbot, button, decision):
    window.dispatch(confirm_event())
    assert window.edith_panel.banner.isVisible()

    qtbot.mouseClick(getattr(window.edith_panel, button), Qt.MouseButton.LeftButton)

    assert window.sent == [{"type": "confirm", "task_id": "t1", "decision": decision}]
    assert not window.edith_panel.banner.isVisible()


def test_allow_always_hidden_when_not_offered(window):
    window.dispatch(confirm_event("shell.run", allow_always=False))

    assert window.edith_panel.allow_button.isVisible()
    assert window.edith_panel.deny_button.isVisible()
    assert not window.edith_panel.always_button.isVisible()


def test_allow_always_visible_and_enabled_when_offered(window):
    window.dispatch(confirm_event("filesystem.delete_file", allow_always=True))

    assert window.edith_panel.always_button.isVisible()
    assert window.edith_panel.always_button.isEnabled()


def test_audit_filter_combo_filters_rows(window, tmp_path):
    path = tmp_path / AUDIT_FILE
    path.parent.mkdir(parents=True)
    lines = [
        {
            "ts": "2026-11-01T09:00:00Z",
            "agent": "viernes",
            "tool": "a",
            "verdict": "allow",
            "rule": "r",
            "user_decision": None,
        },
        {
            "ts": "2026-11-01T09:00:01Z",
            "agent": "viernes",
            "tool": "b",
            "verdict": "deny",
            "rule": "r",
            "user_decision": None,
        },
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    window.presenters.edith.load_audit()
    table = window.edith_panel.audit

    assert table.rowCount() == 2
    window.edith_panel.filter.setCurrentText("deny")
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "b"


def test_pin_dialog_hidden_input_countdown_and_cancel(window, qtbot):
    window.dispatch(ev.auth("locked", "wrong_pin", 10))
    dialog = window.pin_dialog

    assert dialog.isVisible()
    assert dialog.field.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.field.isEnabled()
    assert "10" in dialog.countdown.text()

    window.clock.now = 10
    window.presenters.pin.tick()
    assert dialog.field.isEnabled()

    qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
    assert window.sent == [{"type": "unlock", "pin": None}]
    assert not dialog.isVisible()


def test_pin_dialog_submits_the_pin(window, qtbot):
    window.dispatch(ev.auth("locked", "start", 0))

    qtbot.keyClicks(window.pin_dialog.field, "4821")
    qtbot.keyClick(window.pin_dialog.field, Qt.Key.Key_Return)

    assert window.sent == [{"type": "unlock", "pin": "4821"}]
    assert window.pin_dialog.field.text() == ""


def test_no_lock_file_shows_only_an_explanation(window):
    window.dispatch(ev.auth("locked", "no_lock_file", 0))

    assert window.pin_dialog.isVisible()
    assert "tony pin set" in window.pin_dialog.message.text()
    assert not window.pin_dialog.field.isVisible()


def test_unlock_action_available_while_locked(window):
    assert not window.unlock_action.isEnabled()

    window.dispatch(ev.auth("locked", "cancelled", 0))
    assert window.unlock_action.isEnabled()

    window.unlock_action.trigger()
    assert window.pin_dialog.isVisible()
