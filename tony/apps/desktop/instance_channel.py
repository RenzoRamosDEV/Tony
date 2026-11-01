from collections.abc import Mapping
from typing import Literal

InstanceMessage = Literal["show", "focus"]
MESSAGES: tuple[InstanceMessage, ...] = ("show", "focus")
MAX_MESSAGE_BYTES = 16
CLIENT_TIMEOUT_MS = 500


def socket_name(environ: Mapping[str, str], uid: int) -> str:
    """The per-user local socket of the running desktop app."""
    runtime_dir = environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return f"tony-desktop-{uid}"
    flatpak_id = environ.get("FLATPAK_ID")
    if flatpak_id:
        return f"{runtime_dir}/app/{flatpak_id}/tony.sock"
    return f"{runtime_dir}/tony-desktop.sock"


def parse_message(raw: bytes) -> InstanceMessage | None:
    """Exactly `show` or `focus` (one optional trailing newline); anything else is ignored."""
    if len(raw) > MAX_MESSAGE_BYTES:
        return None
    try:
        text = raw.decode("utf-8").removesuffix("\n")
    except UnicodeDecodeError:
        return None
    return next((message for message in MESSAGES if message == text), None)
