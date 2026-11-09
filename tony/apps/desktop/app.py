import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from tony.apps.desktop.bridge import CoreThread, QtEventBridge, Runtime
from tony.apps.desktop.hotkey_spec import Hotkeys, HotkeysFactory, register_hotkey
from tony.apps.desktop.instance_channel import socket_name
from tony.apps.desktop.page_bridge import PageBridge
from tony.apps.desktop.page_policy import missing_build_message, web_dist
from tony.apps.desktop.presenters.attention import ConfirmationAttention, Notifier
from tony.apps.desktop.presenters.tray import TrayPresenter
from tony.apps.desktop.system.single_instance import InstanceServer, send_to_running
from tony.apps.desktop.system.tray import create_tray
from tony.apps.desktop.widgets.main_window import MainWindow
from tony.apps.desktop.widgets.web_view import create_web_view
from tony.apps.desktop.window_controls import WindowControls
from tony.core.config.settings import DesktopSettings, load_config
from tony.core.events import core_events
from tony.core.events.core_events import Publisher

RuntimeFactory = Callable[[Publisher], Runtime]
EventLoop = Callable[[QApplication, MainWindow], int]
ViewFactory = Callable[[QUrl, PageBridge, WindowControls], QWidget]


def default_runtime_factory(root: Path) -> RuntimeFactory:
    from tony.core.guard.caching_wording import cached_wording_factory
    from tony.core.guard.claude_wording import ClaudeWording
    from tony.core.orchestrator.claude_engine import ClaudeEngine
    from tony.core.orchestrator.runtime import CoreRuntime
    from tony.core.voice.engines.loader import load_engines
    from tony.core.voice.service import VoiceService

    wording = cached_wording_factory(ClaudeWording)

    def factory(publish: Publisher) -> Runtime:
        return CoreRuntime(
            root,
            publish,
            chat_engine=ClaudeEngine(),
            engine=ClaudeEngine(),
            wording=wording,
            voice=VoiceService(load_engines),
        )

    return factory


def web_view(home: QUrl, bridge: PageBridge, controls: WindowControls) -> QWidget:
    view = create_web_view(home, bridge, controls)
    view.load(home)
    return view


def _local_now() -> datetime:
    return datetime.now().astimezone()


def open_desktop(
    root: Path,
    runtime_factory: RuntimeFactory,
    *,
    view_factory: ViewFactory = web_view,
    dist: Path | None = None,
) -> tuple[MainWindow, CoreThread]:
    """Show the window on the built page and start the core thread; closing the window stops
    the core. Without a build the window shows how to make one and everything else still runs."""
    events = QtEventBridge()
    core = CoreThread(runtime_factory, events)
    page = PageBridge(core.submit, lambda event: window.report(event), root, now=_local_now)
    window = MainWindow(TrayPresenter(), page, QWidget(), on_close=core.stop)
    controls = WindowControls(window, parent=window)
    window.controls = controls
    index = (dist or web_dist()) / "index.html"
    if index.is_file():
        content = view_factory(QUrl.fromLocalFile(str(index)), page, controls)
    else:
        content = QLabel(missing_build_message(index.parent))
        content.setWordWrap(True)
    window.setCentralWidget(content)
    events.event.connect(window.dispatch)
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


def pynput_hotkeys(mapping: dict[str, Callable[[], None]]) -> Hotkeys:
    from tony.apps.desktop.system.hotkey import PynputHotkeys

    return PynputHotkeys(mapping)


class ClosableNotifier(Notifier, Protocol):
    def close(self) -> None: ...


def desktop_notifications() -> ClosableNotifier:
    from tony.apps.desktop.system.notifier import DesktopNotifications

    return DesktopNotifications()


class Summoner(QObject):
    """Brings `show`/`focus` requests from any thread to the Qt main thread."""

    requested = Signal(str)

    def __init__(self, window: MainWindow, submit: Callable[[dict], None]) -> None:
        super().__init__()
        self._window = window
        self._submit = submit
        self.requested.connect(self.summon)

    @Slot(str)
    def summon(self, message: str) -> None:
        self._window.reveal()
        if message == "focus":
            self._submit({"type": "listen"})


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
    environ: Mapping[str, str] = os.environ,
    hotkeys: HotkeysFactory = pynput_hotkeys,
    notifier: Callable[[], ClosableNotifier] = desktop_notifications,
    view_factory: ViewFactory = web_view,
) -> int:
    """Raise the running instance, or open the app and serve the single-instance channel."""
    # Qt WebEngine must be loaded before the QApplication is created.
    from PySide6 import QtWebEngineWidgets  # noqa: F401

    app = QApplication.instance() or QApplication(sys.argv)
    channel = channel or LocalChannel(socket_name(environ, os.getuid()))
    if channel.send("focus" if focus else "show"):
        return 0
    window, core = open_desktop(
        root, runtime_factory or default_runtime_factory(root), view_factory=view_factory
    )
    app.aboutToQuit.connect(core.stop)

    summoner = Summoner(window, core.submit)
    channel.serve(summoner.summon)
    settings = desktop_settings(root)
    tray = create_tray(window, window.tray_presenter, enabled=settings.tray, quit=app.quit)
    hotkey = register_hotkey(
        settings.hotkey,
        environ,
        lambda: summoner.requested.emit("focus"),
        hotkeys,
        lambda source, message: window.dispatch(core_events.error(source, message)),
    )
    notifications = notifier()
    attention = ConfirmationAttention(
        notifications,
        window_hidden=lambda: not window.isVisible() or window.isMinimized(),
        reveal=lambda confirmation: window.reveal(confirmation=confirmation),
        report=window.dispatch,
    )
    window.dispatched.connect(attention.apply)
    if focus:
        summoner.summon("focus")
    try:
        return run_loop(app, window)
    finally:
        if hotkey is not None:
            hotkey.stop()
        if tray is not None:
            tray.hide()
        notifications.close()
        channel.close()
        core.stop()
