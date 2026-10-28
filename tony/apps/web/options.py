"""Options of `tony web`; importable without the web extra so the CLI can validate them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tony.core.channels.bootstrap import RuntimeOptions

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class WebOptions:
    host: str
    port: int
    runtime: RuntimeOptions
    open_browser: bool = False
    dist_dir: Path | None = None

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/"


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS
