import re
from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def section(title: str) -> str:
    match = re.search(rf"^#+ {re.escape(title)}\n(.*?)(?=^#+ |\Z)", README, re.M | re.S)
    assert match, title
    return match.group(1)


def test_flatpak_section_documents_the_local_build():
    text = section("Flatpak")
    assert "flatpak-builder --user --install --force-clean build-dir" in text
    assert "packaging/io.github.renzoramosdev.Tony.yml" in text
    assert "flatpak run io.github.renzoramosdev.Tony" in text
    assert "flatpak override --user --env=TONY_HOME=" in text
    assert "uv export --frozen --no-dev --extra voice --extra desktop --no-emit-project" in text


def test_wayland_shortcuts_run_tony_focus():
    text = section("Atajos en Wayland")
    assert "tony --focus" in text and "flatpak run io.github.renzoramosdev.Tony --focus" in text


def test_mcp_note_recommends_uvx_over_npx():
    text = section("Flatpak")
    assert "npx" in text and "uvx" in text
