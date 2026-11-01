import socket
import time

import pytest

from tony.apps.desktop.system.single_instance import InstanceServer, send_to_running


@pytest.fixture
def name(tmp_path):
    return str(tmp_path / "tony-desktop.sock")


@pytest.fixture
def server(qtbot):
    servers = []

    def serve(name):
        server = InstanceServer()
        server.serve(name)
        servers.append(server)
        return server

    yield serve
    for server in servers:
        server.close()


def test_a_served_channel_receives_focus(qtbot, name, server):
    running = server(name)
    with qtbot.waitSignal(running.message, timeout=5000) as received:
        assert send_to_running(name, "focus")
    assert received.args == ["focus"]


def test_show_is_received_too(qtbot, name, server):
    running = server(name)
    with qtbot.waitSignal(running.message, timeout=5000) as received:
        assert send_to_running(name, "show")
    assert received.args == ["show"]


def test_no_instance_answers_within_half_a_second(name):
    started = time.monotonic()
    assert send_to_running(name, "show") is False
    assert time.monotonic() - started < 0.5


def test_a_stale_socket_file_is_replaced(qtbot, name, server):
    stale = socket.socket(socket.AF_UNIX)
    stale.bind(name)
    stale.close()
    running = server(name)
    with qtbot.waitSignal(running.message, timeout=5000):
        assert send_to_running(name, "focus")


def test_unknown_messages_are_ignored(qtbot, name, server):
    running = server(name)
    received = []
    running.message.connect(received.append)
    assert send_to_running(name, "record")
    with qtbot.waitSignal(running.message, timeout=5000):
        assert send_to_running(name, "show")
    assert received == ["show"]
