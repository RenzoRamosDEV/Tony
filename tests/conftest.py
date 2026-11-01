import os

import pytest

pytest_plugins = ["pytester"]

_SKIP_EVALS = pytest.mark.skip(reason="real-model eval: set TONY_EVALS=1 to run")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TONY_EVALS") == "1":
        return
    for item in items:
        if item.get_closest_marker("evals"):
            item.add_marker(_SKIP_EVALS)
