"""PreferencesStore (specs/user-memory: directorio, preferencias, bloque de inyección)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from tony.core.config import atomic
from tony.core.memory.preferences import OMITTED_HEADER, PreferencesStore

TODAY = date(2026, 10, 28)


def store(tmp_path: Path, max_lines: int = 200) -> PreferencesStore:
    return PreferencesStore(tmp_path / "memory" / "preferences.md", max_lines=max_lines)


def test_first_read_creates_the_directory_and_returns_nothing(tmp_path: Path) -> None:
    prefs = store(tmp_path)

    assert prefs.read() == []
    assert (tmp_path / "memory").is_dir()
    assert not prefs.path.exists()


def test_append_keeps_previous_content_and_formats_the_line(tmp_path: Path) -> None:
    prefs = store(tmp_path)
    prefs.path.parent.mkdir()
    prefs.path.write_text("- [2026-10-28] Prefiere respuestas cortas\n", encoding="utf-8")

    line = prefs.append('Llamarle "señor"', today=TODAY)

    assert line == '- [2026-10-28] Llamarle "señor"'
    assert prefs.read() == [
        "- [2026-10-28] Prefiere respuestas cortas",
        '- [2026-10-28] Llamarle "señor"',
    ]
    assert prefs.path.read_text(encoding="utf-8").endswith('Llamarle "señor"\n')


def test_append_to_a_missing_file_creates_it(tmp_path: Path) -> None:
    prefs = store(tmp_path)

    prefs.append("x", today=TODAY)

    assert prefs.read() == ["- [2026-10-28] x"]


def test_append_to_a_file_without_trailing_newline_starts_a_new_line(tmp_path: Path) -> None:
    prefs = store(tmp_path)
    prefs.path.parent.mkdir()
    prefs.path.write_text("- [2026-10-27] a", encoding="utf-8")

    prefs.append("b", today=TODAY)

    assert prefs.read() == ["- [2026-10-27] a", "- [2026-10-28] b"]


def test_failed_replace_leaves_the_original_intact_and_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = store(tmp_path)
    prefs.path.parent.mkdir()
    prefs.path.write_text("a\nb\nc\n", encoding="utf-8")

    def failing_replace(src, dst):
        raise OSError("disco lleno")

    monkeypatch.setattr(atomic.os, "replace", failing_replace)

    with pytest.raises(OSError):
        prefs.append("d", today=TODAY)

    assert prefs.path.read_text(encoding="utf-8") == "a\nb\nc\n"
    assert sorted(p.name for p in prefs.path.parent.iterdir()) == ["preferences.md"]


def test_write_atomic_replaces_the_target(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old", encoding="utf-8")

    atomic.write_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert os.listdir(tmp_path) == ["f.txt"]


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    prefs = store(tmp_path)
    prefs.path.parent.mkdir()
    prefs.path.write_text("- [2026-10-28] a\n\n   \n- [2026-10-28] b\n", encoding="utf-8")

    assert prefs.read() == ["- [2026-10-28] a", "- [2026-10-28] b"]


def write_lines(prefs: PreferencesStore, count: int) -> None:
    prefs.path.parent.mkdir(exist_ok=True)
    prefs.path.write_text("".join(f"- [2026-10-28] p{i}\n" for i in range(1, count + 1)))


def test_injection_block_at_the_limit_has_no_header(tmp_path: Path) -> None:
    prefs = store(tmp_path)
    write_lines(prefs, 200)

    block = prefs.injection_block()

    assert block.splitlines()[0] == "- [2026-10-28] p1"
    assert len(block.splitlines()) == 200
    assert "omitidas" not in block


def test_injection_block_over_the_limit_keeps_the_last_lines_with_a_header(
    tmp_path: Path,
) -> None:
    prefs = store(tmp_path)
    write_lines(prefs, 205)

    lines = prefs.injection_block().splitlines()

    assert lines[0] == "(…5 líneas anteriores omitidas; ejecuta /memoria para verlas)"
    assert lines[1] == "- [2026-10-28] p6"
    assert lines[-1] == "- [2026-10-28] p205"
    assert len(lines) == 201
    assert len(prefs.read()) == 205
    assert OMITTED_HEADER.format(count=5) == lines[0]


def test_injection_block_one_over_the_limit(tmp_path: Path) -> None:
    prefs = store(tmp_path, max_lines=3)
    write_lines(prefs, 4)

    lines = prefs.injection_block().splitlines()

    assert lines[0] == "(…1 líneas anteriores omitidas; ejecuta /memoria para verlas)"
    assert lines[1:] == ["- [2026-10-28] p2", "- [2026-10-28] p3", "- [2026-10-28] p4"]


def test_injection_block_of_an_empty_file_is_empty(tmp_path: Path) -> None:
    assert store(tmp_path).injection_block() == ""
