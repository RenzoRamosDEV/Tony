import configparser
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
APP_ID = "io.github.renzoramosdev.Tony"
FINISH_ARGS = {
    "--socket=wayland",
    "--socket=fallback-x11",
    "--socket=pulseaudio",
    "--share=network",
    "--filesystem=home",
    "--talk-name=org.freedesktop.Notifications",
    "--device=dri",
    "--env=QTWEBENGINE_DISABLE_SANDBOX=1",
}
NPM_CI = "npm --prefix tony/apps/desktop/web ci"
NPM_BUILD = "npm --prefix tony/apps/desktop/web run build"


def manifest():
    return yaml.safe_load((PACKAGING / f"{APP_ID}.yml").read_text(encoding="utf-8"))


def module(name):
    [found] = [m for m in manifest()["modules"] if isinstance(m, dict) and m["name"] == name]
    return found


def desktop_entry():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(PACKAGING / f"{APP_ID}.desktop", encoding="utf-8")
    return parser


def test_manifest_identity_and_runtime():
    data = manifest()
    assert (data["id"], data["command"]) == (APP_ID, "tony")
    assert (data["runtime"], data["sdk"]) == ("org.kde.Platform", "org.kde.Sdk")
    assert data["runtime-version"] == "6.8"


def test_finish_args_are_exactly_the_required_set():
    args = manifest()["finish-args"]
    assert set(args) == FINISH_ARGS and len(args) == len(FINISH_ARGS)


def test_portaudio_module_is_pinned_by_sha256():
    [source] = module("portaudio")["sources"]
    assert source["type"] == "archive" and "v19.7.0" in source["url"]
    assert len(source["sha256"]) == 64 and int(source["sha256"], 16) >= 0


def test_tony_is_installed_from_hash_pinned_requirements():
    tony = module("tony")
    commands = "\n".join(tony["build-commands"])
    assert "--require-hashes -r packaging/requirements.txt" in commands
    assert "--no-deps ." in commands
    assert f"share/applications/{APP_ID}.desktop" in commands
    assert f"share/icons/hicolor/scalable/apps/{APP_ID}.svg" in commands
    assert {"type": "dir", "path": ".."} in tony["sources"]


def test_requirements_are_hash_pinned_and_include_the_extras():
    text = (PACKAGING / "requirements.txt").read_text(encoding="utf-8")
    assert "--hash=sha256:" in text
    for package in ("faster-whisper", "kokoro", "torch", "desktop-notifier", "pyside6"):
        assert f"\n{package}==" in text


def test_desktop_file():
    entry = desktop_entry()
    main = entry["Desktop Entry"]
    assert (main["Type"], main["Name"], main["Exec"], main["Icon"]) == (
        "Application",
        "Tony",
        "tony",
        APP_ID,
    )
    actions = [section for section in entry.sections() if section.startswith("Desktop Action ")]
    assert [entry[action]["Exec"] for action in actions] == ["tony --focus"]


def test_scalable_icon_exists():
    icon = PACKAGING / f"{APP_ID}.svg"
    assert icon.read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_the_built_web_front_ships_in_the_wheel():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "tony/apps/desktop/web/dist/**" in wheel["artifacts"]
    assert "tony/apps/desktop/web/node_modules" in wheel["exclude"]


def test_the_node_sdk_extension_is_available_to_the_build():
    data = manifest()
    assert "org.freedesktop.Sdk.Extension.node20" in data["sdk-extensions"]
    assert "/usr/lib/sdk/node20/bin" in module("tony")["build-options"]["append-path"]


def test_the_web_front_is_built_before_tony_is_installed():
    commands = module("tony")["build-commands"]
    first_pip = next(i for i, command in enumerate(commands) if command.startswith("pip3 install"))
    assert commands.index(NPM_CI) < commands.index(NPM_BUILD) < first_pip
