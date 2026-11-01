from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

NATIVE_SERVER = "tony"


@dataclass(frozen=True)
class NativeTool:
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], Awaitable[str]]


NATIVE_TOOLS: dict[str, NativeTool] = {}
