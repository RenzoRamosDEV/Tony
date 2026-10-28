"""EngineRegistry: one lazy instance per engine; availability without loading (voice-engines)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tests.fakes.voice import FakeStt, FakeTts, FakeVad
from tony.core.config import VoiceSettings
from tony.core.voice.engines import (
    EXTRA_HINT,
    REQUIRED_MODULES,
    EngineRegistry,
    VoiceAvailability,
    voice_availability,
)
from tony.core.voice.ports import VoiceConfigError


class Factories:
    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[tuple[str, str]] = []
        self.delay_s = delay_s

    def vad(self) -> FakeVad:
        self.calls.append(("vad", ""))
        return FakeVad()

    def stt(self, model: str) -> FakeStt:
        time.sleep(self.delay_s)
        self.calls.append(("stt", model))
        return FakeStt("x")

    def tts(self, voice: str) -> FakeTts:
        self.calls.append(("tts", voice))
        return FakeTts()


def registry(factories: Factories, **settings: Any) -> EngineRegistry:
    return EngineRegistry(
        VoiceSettings(**settings),
        vad_factory=factories.vad,
        stt_factory=factories.stt,
        tts_factory=factories.tts,
    )


def test_each_engine_is_built_once_and_shared() -> None:
    factories = Factories()
    engines = registry(factories)

    first, second = engines.get_stt("faster-whisper/small"), engines.get_stt("faster-whisper/small")
    engines.get_vad(), engines.get_vad()
    engines.get_tts("kokoro/ef_dora"), engines.get_tts("kokoro/ef_dora")

    assert first is second
    assert factories.calls == [("stt", "small"), ("vad", ""), ("tts", "ef_dora")]


def test_two_threads_loading_the_same_model_share_one_instance() -> None:
    factories = Factories(delay_s=0.05)
    engines = registry(factories)
    seen: list[Any] = []
    threads = [
        threading.Thread(target=lambda: seen.append(engines.get_stt("faster-whisper/base")))
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(seen) == 2 and seen[0] is seen[1]
    assert factories.calls == [("stt", "base")]


def test_an_invalid_alias_is_rejected_before_loading() -> None:
    factories = Factories()
    engines = registry(factories)

    with pytest.raises(VoiceConfigError, match="kokoro/no_existe"):
        engines.get_tts("kokoro/no_existe")
    with pytest.raises(VoiceConfigError, match="whisper/small"):
        engines.get_stt("whisper/small")

    assert factories.calls == []


def test_warmup_loads_the_three_configured_engines_and_times_them() -> None:
    factories = Factories()
    engines = registry(factories, stt="faster-whisper/base", tts="kokoro/em_alex")

    timings = engines.warmup()

    assert list(timings) == ["vad", "stt", "tts"]
    assert all(isinstance(ms, int) and ms >= 0 for ms in timings.values())
    assert factories.calls == [("vad", ""), ("stt", "base"), ("tts", "em_alex")]
    assert engines.stt_alias == "faster-whisper/base" and engines.tts_voice == "em_alex"


def test_availability_is_false_with_the_extra_hint_when_a_module_is_missing() -> None:
    def find_spec(name: str) -> object | None:
        return None if name == "kokoro" else object()

    result = voice_availability(VoiceSettings(), find_spec=find_spec)

    assert result == VoiceAvailability(
        available=False,
        reason=f"extra tony[voice] no instalado (falta kokoro): {EXTRA_HINT}",
        stt="faster-whisper/small",
        tts="kokoro/ef_dora",
    )
    assert result.as_dict() == {
        "available": False,
        "reason": result.reason,
        "stt": "faster-whisper/small",
        "tts": "kokoro/ef_dora",
    }


def test_availability_is_false_with_an_invalid_alias_even_with_the_modules() -> None:
    result = voice_availability(
        VoiceSettings(tts="kokoro/no_existe"), find_spec=lambda name: object()
    )

    assert result.available is False
    assert result.reason is not None and result.reason.startswith("voice.tts: ")


def test_availability_is_true_without_loading_anything() -> None:
    checked: list[str] = []

    def find_spec(name: str) -> object:
        checked.append(name)
        return object()

    result = voice_availability(VoiceSettings(), find_spec=find_spec)

    assert result == VoiceAvailability(True, None, "faster-whisper/small", "kokoro/ef_dora")
    assert set(checked) == set(REQUIRED_MODULES)
    assert {"faster_whisper", "kokoro", "silero_vad", "onnxruntime"} <= set(REQUIRED_MODULES)
