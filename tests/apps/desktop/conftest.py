import gc

import pytest


@pytest.fixture(autouse=True)
def collect_qt_garbage_on_main_thread():
    """Free cyclic Qt wrappers left by a test on the main thread.

    Otherwise the cyclic GC may free them later from the core thread, and Shiboken's
    deferred main-thread deletion then crashes (SIGSEGV in runDeletionInMainThread).
    """
    yield
    gc.collect()
