"""SettingsStore: tolerant reads, validated reply_mode, atomic exact writes."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tony.core.memory.settings import SettingsStore, UserSettings


def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "memory" / "settings.json")


def test_missing_file_gives_empty_settings(tmp_path: Path) -> None:
    assert store(tmp_path).load() == UserSettings(reply_mode=None)


@pytest.mark.parametrize("content", ["{not json", "", "[]", '"text"'])
def test_invalid_content_gives_empty_settings_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    s = store(tmp_path)
    s.path.parent.mkdir()
    s.path.write_text(content, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        settings = s.load()

    assert settings.reply_mode is None
    assert any("settings.json" in record.message for record in caplog.records)


def test_value_out_of_domain_is_dropped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    s = store(tmp_path)
    s.path.parent.mkdir()
    s.path.write_text('{"reply_mode": "loud"}', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        settings = s.load()

    assert settings.reply_mode is None
    assert any("loud" in record.message for record in caplog.records)


@pytest.mark.parametrize("mode", ["auto", "voice", "text", "both"])
def test_valid_modes_are_read(tmp_path: Path, mode: str) -> None:
    s = store(tmp_path)
    s.path.parent.mkdir()
    s.path.write_text(json.dumps({"reply_mode": mode}), encoding="utf-8")

    assert s.load().reply_mode == mode


def test_set_reply_mode_writes_exactly_the_object_and_reads_back(tmp_path: Path) -> None:
    s = store(tmp_path)

    s.set_reply_mode("text")

    assert json.loads(s.path.read_text(encoding="utf-8")) == {"reply_mode": "text"}
    assert s.path.read_text(encoding="utf-8") == '{"reply_mode": "text"}'
    assert s.load().reply_mode == "text"


def test_set_reply_mode_rejects_unknown_values_without_writing(tmp_path: Path) -> None:
    s = store(tmp_path)

    with pytest.raises(ValueError):
        s.set_reply_mode("loud")

    assert not s.path.exists()
