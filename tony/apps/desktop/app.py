import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tony.apps.desktop.bridge import CoreThread, QtEventBridge, Runtime
from tony.apps.desktop.presenters.bundle import Presenters
from tony.apps.desktop.widgets.main_window import MainWindow
from tony.core.events.core_events import Publisher

RuntimeFactory = Callable[[Publisher], Runtime]
EventLoop = Callable[[QApplication, MainWindow], int]


def default_runtime_factory(root: Path) -> RuntimeFactory:
    from tony.core.guard.claude_wording import ClaudeWording
    from tony.core.orchestrator.claude_engine import ClaudeEngine
    from tony.core.orchestrator.runtime import CoreRuntime

    def factory(publish: Publisher) -> Runtime:
        return CoreRuntime(
            root, publish, chat_engine=ClaudeEngine(), engine=ClaudeEngine(), wording=ClaudeWording
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


def launch(
    root: Path,
    runtime_factory: RuntimeFactory | None = None,
    *,
    run_loop: EventLoop = lambda app, window: app.exec(),
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window, core = open_desktop(root, runtime_factory or default_runtime_factory(root))
    app.aboutToQuit.connect(core.stop)
    try:
        return run_loop(app, window)
    finally:
        core.stop()
