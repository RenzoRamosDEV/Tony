"""Task identifiers."""

from __future__ import annotations

import uuid


def new_task_id() -> str:
    """Unique 32-char hex id (uuid4); a ULID would satisfy the same contract."""
    return uuid.uuid4().hex
