import json
from datetime import datetime, timedelta, timezone

import pytest

from tony.apps.desktop.page_bridge import PageBridge
from tony.core.events import core_events as ev
from tony.core.guard.audit import AUDIT_FILE

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone(timedelta(hours=1)))


class Page:
    def __init__(self, bridge):
        self.received = []
        bridge.event.connect(lambda text: self.received.append(json.loads(text)))


@pytest.fixture
def made(qapp, tmp_path):
    submitted, reported = [], []
    bridge = PageBridge(submitted.append, reported.append, tmp_path, now=lambda: NOW)
    return bridge, Page(bridge), submitted, reported


def test_events_before_ready_are_not_emitted(made):
    bridge, page, *_ = made
    bridge.publish(ev.token("jarvis", "Hola"))
    assert page.received == []


def test_ready_replays_the_snapshot_then_forwards_live_events_in_order(made):
    bridge, page, *_ = made
    state = [
        ev.voice_state("loading"),
        ev.auth("locked", "start", 0),
        ev.mcp_status("viernes", "filesystem", up=True, reason=None),
    ]
    for event in state:
        bridge.publish(event)
    bridge.publish(ev.token("jarvis", "perdido"))
    bridge.ready()
    live = [ev.token("jarvis", "Hola"), ev.voice_state("ready")]
    for event in live:
        bridge.publish(event)
    assert page.received == state + live


def test_events_reach_the_page_as_unchanged_json_text(made):
    bridge, *_ = made
    texts = []
    bridge.event.connect(texts.append)
    bridge.ready()
    event = ev.token("jarvis", "¿Qué tal, señor?")
    bridge.publish(event)
    assert [json.loads(text) for text in texts] == [event]


def test_voice_levels_are_forwarded_live_but_not_replayed(made):
    bridge, page, *_ = made
    bridge.publish(ev.voice_level("input", 0.4))
    bridge.ready()
    level = ev.voice_level("output", 0.6)
    bridge.publish(level)
    assert page.received == [level]


def test_a_second_ready_replays_again(made):
    bridge, page, *_ = made
    state = ev.reply_mode("voice")
    bridge.publish(state)
    bridge.ready()
    bridge.ready()
    assert page.received == [state, state]


def test_accepted_commands_are_submitted(made):
    bridge, page, submitted, reported = made
    bridge.ready()
    bridge.send('{"type": "confirm", "task_id": "t1", "decision": "allow"}')
    assert submitted == [{"type": "confirm", "task_id": "t1", "decision": "allow"}]
    assert page.received == [] and reported == []


def test_rejected_commands_are_shown_and_reported_but_not_submitted(made):
    bridge, page, submitted, reported = made
    bridge.ready()
    bridge.send('{"type": "stop"}')
    assert submitted == []
    [error] = page.received
    assert (error["type"], error["source"]) == ("error", "stop")
    assert reported == [error]


def test_audit_today_returns_the_rows_as_json(made, tmp_path):
    bridge, *_ = made
    path = tmp_path / AUDIT_FILE
    path.parent.mkdir(parents=True)
    line = {
        "ts": "2026-11-01T10:00:00Z",
        "agent": "viernes",
        "tool": "shell.run",
        "args_preview": "{}",
        "verdict": "deny",
        "rule": "r/deny",
        "user_decision": None,
    }
    path.write_text(json.dumps(line) + "\n")
    assert json.loads(bridge.auditToday()) == [
        {
            "time": "11:00:00",
            "agent": "viernes",
            "tool": "shell.run",
            "verdict": "deny",
            "rule": "r/deny",
            "user_decision": None,
        }
    ]


def test_audit_today_without_audit_is_an_empty_list(made):
    bridge, *_ = made
    assert bridge.auditToday() == "[]"
