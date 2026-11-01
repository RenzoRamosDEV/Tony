"""Where the embedded page comes from and where it may go: only its own `index.html`, with
`http`/`https` link clicks handed to the system browser and everything else blocked."""

from pathlib import Path
from typing import Literal
from urllib.parse import urldefrag, urlsplit

NavigationDecision = Literal["allow", "external", "block"]

BUILD_COMMAND = (
    "npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build"
)
_EXTERNAL_SCHEMES = {"http", "https"}


def navigation_decision(url: str, home: str, *, link_click: bool) -> NavigationDecision:
    if url and urldefrag(url).url == urldefrag(home).url:
        return "allow"
    parts = urlsplit(url)
    if link_click and parts.scheme.lower() in _EXTERNAL_SCHEMES and parts.netloc:
        return "external"
    return "block"


def web_dist() -> Path:
    return Path(__file__).parent / "web" / "dist"


def missing_build_message(dist: Path) -> str:
    return (
        f"No se encuentra la interfaz web ({dist / 'index.html'}).\n"
        f"Compílala desde la raíz del repositorio con:\n\n{BUILD_COMMAND}"
    )
