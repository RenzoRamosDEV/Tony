"""EngineRegistry: one lazy instance per engine; availability without loading (voice-engines)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tests.fakes.voice import FakeStt, FakeTts, FakeVad
from tony.core.config import VoiceSettings
from tony.core.voice import engines as engines_module
from tony.core.voice.aliases import VoiceAlias, parse_alias
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
        self.calls: list[tuple[Any, ...]] = []
        self.delay_s = delay_s

    def vad(self) -> FakeVad:
        self.calls.append(("vad", ""))
        return FakeVad()

    def stt(self, alias: VoiceAlias, threads: int) -> FakeStt:
        time.sleep(self.delay_s)
        self.calls.append(("stt", alias.name))
        self.stt_threads = threads
        return FakeStt("x")

    def tts(self, alias: VoiceAlias, threads: int) -> FakeTts:
        self.calls.append(("tts", alias.name))
        self.tts_alias = alias
        self.tts_threads = threads
        return FakeTts()


def registry(factories: Factories, cpu_count: int | None = 12, **settings: Any) -> EngineRegistry:
    return EngineRegistry(
        VoiceSettings(**settings),
        vad_factory=factories.vad,
        stt_factory=factories.stt,
        tts_factory=factories.tts,
        cpu_count=lambda: cpu_count,
    )


def test_each_engine_is_built_once_and_shared() -> None:
    factories = Factories()
    engines = registry(factories)

    first, second = engines.get_stt("faster-whisper/small"), engines.get_stt("faster-whisper/small")
    engines.get_vad(), engines.get_vad()
    engines.get_tts("kokoro/ef_dora"), engines.get_tts("kokoro/ef_dora")

    assert first is second
    assert factories.calls == [("stt", "small"), ("vad", ""), ("tts", "ef_dora")]


def test_each_full_alias_is_built_once() -> None:
    factories = Factories()
    engines = registry(factories)

    slow = engines.get_tts("piper/es_MX-ald-medium?speed=0.9")
    again = engines.get_tts("piper/es_MX-ald-medium?speed=0.9")
    fast = engines.get_tts("piper/es_MX-ald-medium?speed=1.1")

    assert slow is again and slow is not fast
    assert [c for c in factories.calls if c[0] == "tts"] == [
        ("tts", "es_MX-ald-medium"),
        ("tts", "es_MX-ald-medium"),
    ]
    assert factories.tts_alias.speed == 1.1


@pytest.mark.parametrize(
    ("cpu_threads", "cpu_count", "expected"),
    [(6, 12, 6), (None, 12, 6), (None, 1, 1), (None, None, 1), (3, 1, 3)],
)
def test_cpu_threads_reach_the_stt_and_tts_factories(
    cpu_threads: int | None, cpu_count: int | None, expected: int
) -> None:
    factories = Factories()
    engines = registry(factories, cpu_count=cpu_count, cpu_threads=cpu_threads)

    engines.get_stt("faster-whisper/base")
    engines.get_tts("kokoro/em_alex")

    assert factories.stt_threads == expected
    assert factories.tts_threads == expected


def test_load_tts_builds_the_engine_named_by_the_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[tuple[str, str, int]] = []

    def loader(engine: str):
        def build(alias: VoiceAlias, threads: int) -> FakeTts:
            built.append((engine, alias.name, threads))
            return FakeTts()

        return build

    monkeypatch.setattr(
        engines_module, "TTS_LOADERS", {"kokoro": loader("kokoro"), "piper": loader("piper")}
    )

    engines_module.load_tts(parse_alias("piper/es_MX-ald-medium"), 4)
    engines_module.load_tts(parse_alias("kokoro/em_alex*0.6+em_santa*0.4"), 6)

    assert built == [("piper", "es_MX-ald-medium", 4), ("kokoro", "em_alex*0.6+em_santa*0.4", 6)]


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
        return None if name == "piper" else object()

    result = voice_availability(VoiceSettings(), find_spec=find_spec)

    assert result == VoiceAvailability(
        available=False,
        reason=f"extra tony[voice] no instalado (falta piper): {EXTRA_HINT}",
        stt="faster-whisper/base",
        tts="piper/es_MX-ald-medium?speed=0.95",
    )
    assert result.as_dict() == {
        "available": False,
        "reason": result.reason,
        "stt": "faster-whisper/base",
        "tts": "piper/es_MX-ald-medium?speed=0.95",
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

    result = voice_availability(VoiceSettings(tts="kokoro/ef_dora"), find_spec=find_spec)

    assert result == VoiceAvailability(True, None, "faster-whisper/base", "kokoro/ef_dora")
    assert set(checked) == {*REQUIRED_MODULES, "kokoro"}
    assert {"faster_whisper", "silero_vad", "onnxruntime", "numpy"} <= set(REQUIRED_MODULES)


@pytest.mark.parametrize(
    ("tts", "needed", "ignored"),
    [
        ("piper/es_MX-ald-medium?speed=0.95", "piper", "kokoro"),
        ("kokoro/em_alex", "kokoro", "piper"),
    ],
)
def test_availability_requires_the_module_of_the_configured_tts_engine(
    tts: str, needed: str, ignored: str
) -> None:
    without_needed = voice_availability(
        VoiceSettings(tts=tts), find_spec=lambda name: None if name == needed else object()
    )
    without_ignored = voice_availability(
        VoiceSettings(tts=tts), find_spec=lambda name: None if name == ignored else object()
    )

    assert without_needed.available is False and f"falta {needed}" in str(without_needed.reason)
    assert without_ignored.available is True
