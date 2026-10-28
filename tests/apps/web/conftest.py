"""The web tests need the `tony[web]` extra; without it the whole package is skipped."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
