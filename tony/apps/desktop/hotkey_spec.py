import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol

HOTKEY_FIELD = "desktop.hotkey"
X11 = "x11"
_MODIFIERS = {
    "super": "<cmd>",
    "meta": "<cmd>",
    "win": "<cmd>",
    "ctrl": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
}
_NAMED_KEYS = {"space": "<space>", "enter": "<enter>", "tab": "<tab>", "esc": "<esc>"}
_FUNCTION_KEY = re.compile(r"^f([1-9]|1[0-2])$")
_CHARACTER_KEY = re.compile(r"^[a-z0-9]$")


class InvalidHotkey(ValueError):
    def __init__(self, spec: str) -> None:
        super().__init__(
            f"{HOTKEY_FIELD} '{spec}' is not valid: use modifiers (Super, Ctrl, Alt, Shift) "
            "and one key (a letter, a digit, F1-F12, Space, Enter, Tab or Esc), e.g. Super+J"
        )


def to_pynput(spec: str) -> str:
    """`Super+J` -> `<cmd>+j`, the pynput GlobalHotKeys syntax."""
    *modifiers, key = (part.strip().lower() for part in spec.split("+"))
    if not modifiers or any(modifier not in _MODIFIERS for modifier in modifiers):
        raise InvalidHotkey(spec)
    combo = [_MODIFIERS[modifier] for modifier in modifiers]
    if len(set(combo)) != len(combo):
        raise InvalidHotkey(spec)
    return "+".join([*combo, _key(key, spec)])


def _key(key: str, spec: str) -> str:
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if _FUNCTION_KEY.match(key):
        return f"<{key}>"
    if _CHARACTER_KEY.match(key):
        return key
    raise InvalidHotkey(spec)


class Hotkeys(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


HotkeysFactory = Callable[[dict[str, Callable[[], None]]], Hotkeys]
Report = Callable[[str, str], Any]


def register_hotkey(
    spec: str,
    environ: Mapping[str, str],
    on_activate: Callable[[], None],
    hotkeys: HotkeysFactory,
    report: Report,
) -> Hotkeys | None:
    """Register the global hotkey on X11 only; problems are reported, never raised."""
    if environ.get("XDG_SESSION_TYPE") != X11:
        return None
    try:
        registered = hotkeys({to_pynput(spec): on_activate})
        registered.start()
    except Exception as error:
        report(HOTKEY_FIELD, str(error) or type(error).__name__)
        return None
    return registered
