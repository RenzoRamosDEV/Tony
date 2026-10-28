"""Front prompts: stable system prompt and per-turn preamble (specs/front-agent)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from tony.core.loader import AgentSpec, Persona, Style
from tony.core.runner.front_prompt import (
    PREAMBLE_END,
    PREAMBLE_START,
    build_front_system_prompt,
    build_turn_preamble,
)
from tony.core.runner.prompt import format_moment
from tony.core.runner.reply_mode import EffectiveMode

SPEC = AgentSpec(
    name="jarvis",
    role="front",
    model="claude-haiku",
    persona=Persona(address="señor", language="es"),
    style=Style(voice="Frases cortas, sin markdown", text="Markdown completo"),
    system_prompt="Eres Jarvis, el asistente de Renzo.",
    path=Path("/tmp/jarvis"),
)


def test_system_prompt_contains_body_native_catalog_criterion_and_contract() -> None:
    prompt = build_front_system_prompt(SPEC, ["delegate", "remember", "set_reply_mode"])

    assert prompt.startswith("Eres Jarvis, el asistente de Renzo.")
    assert "señor" in prompt
    for name in ("delegate", "remember", "set_reply_mode"):
        assert f"`{name}`" in prompt
    assert "datos externos" in prompt and "ficheros" in prompt
    assert "display_text" in prompt and "speech_text" in prompt
    assert PREAMBLE_START in prompt


def test_system_prompt_lists_only_declared_native_tools() -> None:
    prompt = build_front_system_prompt(SPEC, ["remember"])

    assert "`remember`" in prompt
    assert "`delegate`" not in prompt
    assert "`set_reply_mode`" not in prompt
    assert "responde siempre por ti" in prompt


def test_turn_preamble_has_datetime_with_zone_mode_style_and_preferences() -> None:
    now = datetime(2026, 10, 28, 9, 5, 0, tzinfo=timezone(timedelta(hours=2)))

    preamble = build_turn_preamble(
        now, EffectiveMode("voice", "prefix"), SPEC.style, "- [2026-10-28] Prefiere corto"
    )

    assert preamble.startswith(PREAMBLE_START)
    assert preamble.rstrip().endswith(PREAMBLE_END)
    assert "2026-10-28T09:05:00+02:00" in preamble
    assert "voice" in preamble
    assert "Frases cortas, sin markdown" in preamble
    assert "Markdown completo" not in preamble
    assert "- [2026-10-28] Prefiere corto" in preamble


def test_turn_preamble_without_preferences_says_so() -> None:
    preamble = build_turn_preamble(datetime.now(UTC), EffectiveMode("text", "yaml"), SPEC.style, "")

    assert "(ninguna)" in preamble


def test_format_moment_is_shared_with_the_worker_prompt() -> None:
    now = datetime(2026, 10, 28, 9, 5, 0, tzinfo=UTC)

    assert format_moment(now) == "2026-10-28T09:05:00+00:00"
