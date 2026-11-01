import pytest

from tests.fakes.desktop import FakeHotkeys
from tony.apps.desktop.hotkey_spec import HOTKEY_FIELD, InvalidHotkey, register_hotkey, to_pynput


@pytest.mark.parametrize(
    ("spec", "combo"),
    [
        ("Super+J", "<cmd>+j"),
        ("super+j", "<cmd>+j"),
        ("Meta+J", "<cmd>+j"),
        ("Win+J", "<cmd>+j"),
        ("Ctrl+Alt+Space", "<ctrl>+<alt>+<space>"),
        ("Shift+Ctrl+1", "<shift>+<ctrl>+1"),
        ("Super+F2", "<cmd>+<f2>"),
        ("Super+F1", "<cmd>+<f1>"),
        ("Super+F12", "<cmd>+<f12>"),
        ("Alt+Enter", "<alt>+<enter>"),
        ("Alt+Tab", "<alt>+<tab>"),
        ("Ctrl+Esc", "<ctrl>+<esc>"),
        (" Super + J ", "<cmd>+j"),
    ],
)
def test_valid_hotkeys(spec, combo):
    assert to_pynput(spec) == combo


@pytest.mark.parametrize(
    "spec",
    [
        "Super+",
        "J",
        "Super+Hyper+J",
        "Super+F13",
        "Super+F0",
        "",
        "+J",
        "Super+JK",
        "Super+Super+J",
        "Super+Ctrl",
        "Ctrl+J+K",
        "Super+ñ",
    ],
)
def test_invalid_hotkeys_name_the_setting(spec):
    with pytest.raises(InvalidHotkey) as raised:
        to_pynput(spec)
    assert HOTKEY_FIELD == "desktop.hotkey"
    assert HOTKEY_FIELD in str(raised.value)


def register(hotkey="Super+J", session="x11"):
    activations, reports = [], []
    hotkeys = register_hotkey(
        hotkey,
        {"XDG_SESSION_TYPE": session} if session else {},
        lambda: activations.append(1),
        FakeHotkeys,
        lambda source, message: reports.append((source, message)),
    )
    return hotkeys, activations, reports


def test_registered_and_started_on_x11():
    hotkeys, activations, reports = register()
    assert hotkeys.started and list(hotkeys.mapping) == ["<cmd>+j"]
    hotkeys.press("<cmd>+j")
    assert activations == [1] and reports == []


@pytest.mark.parametrize("session", ["wayland", "tty", "", None, "X11"])
def test_not_registered_outside_x11(session):
    hotkeys, _, reports = register(session=session)
    assert hotkeys is None and reports == []


def test_invalid_hotkey_is_reported_and_nothing_registered():
    FakeHotkeys.instances.clear()
    hotkeys, _, reports = register("Super+")
    assert hotkeys is None and FakeHotkeys.instances == []
    [(source, message)] = reports
    assert source == HOTKEY_FIELD and "Super+" in message


def test_a_failing_backend_is_reported():
    def broken(mapping):
        raise OSError("no X display")

    reports = []
    assert (
        register_hotkey(
            "Super+J",
            {"XDG_SESSION_TYPE": "x11"},
            lambda: None,
            broken,
            lambda s, m: reports.append((s, m)),
        )
        is None
    )
    assert reports == [(HOTKEY_FIELD, "no X display")]
