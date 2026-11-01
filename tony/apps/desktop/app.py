import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

from tony.apps.desktop.bridge import CoreThread, QtEventBridge, Runtime
from tony.apps.desktop.instance_channel import socket_name
from tony.apps.desktop.presenters.bundle import Presenters
from tony.apps.desktop.system.single_instance import InstanceServer, send_to_running
from tony.apps.desktop.system.tray import create_tray
from tony.apps.desktop.widgets.main_window import MainWindow
from tony.core.config.settings import DesktopSettings, load_config
from tony.core.events.core_events import Publisher

RuntimeFactory = Callable[[Publisher], Runtime]
EventLoop = Callable[[QApplication, MainWindow], int]


def default_runtime_factory(root: Path) -> RuntimeFactory:
    from tony.core.guard.claude_wording import ClaudeWording
    from tony.core.orchestrator.claude_engine import ClaudeEngine
    from tony.core.orchestrator.runtime import CoreRuntime
    from tony.core.voice.engines.loader import load_engines
    from tony.core.voice.service import VoiceService

    def factory(publish: Publisher) -> Runtime:
        return CoreRuntime(
            root,
            publish,
            chat_engine=ClaudeEngine(),
            engine=ClaudeEngine(),
            wording=ClaudeWording,
            voice=VoiceService(load_engines),
        )

    return factory


def open_desktop(root: Path, runtime_factory: RuntimeFactory) -> tuple[MainWindow, CoreThread]:
    """Show the window and start the core thread; closing the window stops the core."""
    bridge = QtEventBridge()
    core = CoreThread(runtime_factory, bridge)
    presenters = Presenters.create(core.submit, root)
    window = MainWindow(presenters, on_close=core.stop)
    bridge.event.connect(window.dispatch)
    presenters.edith.load_audit()
    window.show()
    core.start()
    return window, core


class InstanceChannel(Protocol):
    def send(self, message: str) -> bool: ...

    def serve(self, on_message: Callable[[str], None]) -> None: ...

    def close(self) -> None: ...


class LocalChannel:
    """The per-user single-instance socket."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._server: InstanceServer | None = None

    def send(self, message: str) -> bool:
        return send_to_running(self._name, message)

    def serve(self, on_message: Callable[[str], None]) -> None:
        self._server = InstanceServer()
        self._server.message.connect(on_message)
        self._server.serve(self._name)

    def close(self) -> None:
        if self._server is not None:
            self._server.close()


def desktop_settings(root: Path) -> DesktopSettings:
    try:
        return load_config(root).desktop
    except Exception:
        return DesktopSettings()


def launch(
    root: Path,
    runtime_factory: RuntimeFactory | None = None,
    *,
    focus: bool = False,
    run_loop: EventLoop = lambda app, window: app.exec(),
    channel: InstanceChannel | None = None,
) -> int:
    """Raise the running instance, or open the app and serve the single-instance channel."""
    app = QApplication.instance() or QApplication(sys.argv)
    channel = channel or LocalChannel(socket_name(os.environ, os.getuid()))
    if channel.send("focus" if focus else "show"):
        return 0
    window, core = open_desktop(root, runtime_factory or default_runtime_factory(root))
    app.aboutToQuit.connect(core.stop)

    def summon(message: str) -> None:
        window.reveal()
        if message == "focus":
            core.submit({"type": "listen"})

    channel.serve(summon)
    settings = desktop_settings(root)
    tray = create_tray(window, window.presenters.tray, enabled=settings.tray, quit=app.quit)
    if focus:
        summon("focus")
    try:
        return run_loop(app, window)
    finally:
        if tray is not None:
            tray.hide()
        channel.close()
        core.stop()
