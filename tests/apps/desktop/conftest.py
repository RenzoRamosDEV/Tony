import gc

import pytest

# Qt WebEngine must be imported before the QApplication (the `qapp` fixture) exists.
from PySide6 import QtWebEngineWidgets  # noqa: F401


@pytest.fixture(autouse=True)
def collect_qt_garbage_on_main_thread():
    """Free cyclic Qt wrappers left by a test on the main thread.

    Otherwise the cyclic GC may free them later from the core thread, and Shiboken's
    deferred main-thread deletion then crashes (SIGSEGV in runDeletionInMainThread).
    """
    yield
    gc.collect()
