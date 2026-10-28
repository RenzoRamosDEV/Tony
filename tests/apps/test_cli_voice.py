"""`tony voice warmup` and `tony voice bench` with a fake engine registry (specs/voice-engines)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.fakes.voice import FakeStt, FakeTts, FakeVad
from tony.apps.cli import main, voice_cli
from tony.core.config import VoiceSettings
from tony.core.voice.engines import EngineRegistry

runner = CliRunner()


class Registries:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.built: list[VoiceSettings] = []
        self.stt = FakeStt("¿qué hora es?")
        self.tts = FakeTts()

    def __call__(self, settings: VoiceSettings) -> EngineRegistry:
        if self.fail is not None:
            raise self.fail
        self.built.append(settings)
        return EngineRegistry(
            settings,
            vad_factory=FakeVad,
            stt_factory=lambda model: self.stt,
            tts_factory=lambda voice: self.tts,
        )


@pytest.fixture
def cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Registries:
    monkeypatch.chdir(tmp_repo)
    (tmp_repo / "config" / "tony.yaml").write_text("", encoding="utf-8")
    registries = Registries()
    monkeypatch.setattr(voice_cli, "registry_factory", registries)
    monkeypatch.delenv("TONY_EVALS", raising=False)
    return registries


def lines(output: str, marker: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(marker)]


def test_warmup_loads_the_three_engines_and_prints_their_times(cli: Registries) -> None:
    result = runner.invoke(main.app, ["voice", "warmup"])

    assert result.exit_code == 0, result.output
    loaded = lines(result.stdout, "✓")
    assert [line.split()[1] for line in loaded] == ["vad", "stt", "tts"]
    assert all(re.search(r"\d+ ms$", line) for line in loaded)
    assert cli.built == [VoiceSettings()]


def test_warmup_without_the_extra_exits_2_with_the_install_hint(
    cli: Registries, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        voice_cli, "registry_factory", Registries(fail=ImportError("No module named 'kokoro'"))
    )

    result = runner.invoke(main.app, ["voice", "warmup"])

    assert result.exit_code == 2
    assert "uv sync --extra voice" in result.output


def test_warmup_with_an_invalid_alias_exits_1_naming_it(cli: Registries) -> None:
    Path("config/tony.yaml").write_text("voice:\n  tts: kokoro/no_existe\n", encoding="utf-8")

    result = runner.invoke(main.app, ["voice", "warmup"])

    assert result.exit_code == 1
    assert "kokoro/no_existe" in result.output


def test_bench_prints_p50_and_p95_of_five_repetitions_without_the_model(
    cli: Registries, monkeypatch: pytest.MonkeyPatch
) -> None:
    roundtrips: list[int] = []
    monkeypatch.setattr(voice_cli, "measure_roundtrip", lambda *a: roundtrips.append(1) or 100)

    result = runner.invoke(main.app, ["voice", "bench"])

    assert result.exit_code == 0, result.output
    for measure in ("load", "stt_3s", "tts_12w"):
        row = next(line for line in result.stdout.splitlines() if line.startswith(measure))
        assert re.search(r"p50 +\d+ ms +p95 +\d+ ms", row), row
    assert "roundtrip" not in result.stdout
    assert roundtrips == []
    assert len(cli.stt.calls) == 5 and all(u.duration_ms == 3_000 for u, _ in cli.stt.calls)
    assert len(cli.tts.sentences) == 5 and len(cli.tts.sentences[0].split()) == 12


@pytest.mark.parametrize(("ms", "flagged"), [(1_999, False), (2_000, False), (2_001, True)])
def test_bench_with_evals_measures_the_roundtrip_against_the_2s_target(
    cli: Registries, monkeypatch: pytest.MonkeyPatch, ms: int, flagged: bool
) -> None:
    monkeypatch.setenv("TONY_EVALS", "1")
    monkeypatch.setattr(voice_cli, "measure_roundtrip", lambda *a: ms)

    result = runner.invoke(main.app, ["voice", "bench"])

    assert result.exit_code == 0, result.output
    row = next(line for line in result.stdout.splitlines() if line.startswith("roundtrip"))
    assert f"p50 {ms:>6} ms" in row
    assert ("objetivo no alcanzado" in row) is flagged


def test_percentiles_use_the_nearest_rank() -> None:
    assert voice_cli.percentiles([5, 1, 4, 2, 3]) == (3, 5)
    assert voice_cli.percentiles([7]) == (7, 7)
    assert voice_cli.percentiles([10, 20]) == (10, 20)


def test_help_is_in_spanish() -> None:
    top = runner.invoke(main.app, ["voice", "--help"]).stdout
    assert "warmup" in top and "bench" in top and "modelos" in top
    bench = runner.invoke(main.app, ["voice", "bench", "--help"]).stdout
    assert "--config" in bench and "TONY_EVALS" in bench


class SilentTts(FakeTts):
    def synthesize(self, text, voice):
        self.sentences.append(text)
        return iter(())


class StuckTts(FakeTts):
    def __init__(self) -> None:
        super().__init__()
        import threading

        self.gate = threading.Event()

    def synthesize(self, text, voice):
        self.gate.wait(timeout=2)
        return super().synthesize(text, voice)


async def first_audio(
    tts, text: str = "Son las diez.", timeout_s: float = 2.0, started_ago_s: float = 0.0
):
    import time

    from tests.fakes.sinks import ListEventSink
    from tony.core.voice.executor import VoiceExecutor

    executor = VoiceExecutor()
    try:
        return await voice_cli.time_to_first_audio(
            lambda: tts,
            executor,
            "ef_dora",
            text,
            ListEventSink(),
            time.perf_counter() - started_ago_s,
            timeout_s,
        )
    finally:
        executor.close()


async def test_review05_finding_15_a_real_first_chunk_gives_its_latency() -> None:
    tts = FakeTts()

    elapsed = await first_audio(tts, started_ago_s=100.0)

    assert 100_000 <= elapsed < 100_090
    assert tts.voices == ["ef_dora"]


class SlowSecondTts(FakeTts):
    def synthesize(self, text, voice):
        if self.sentences:
            import time

            time.sleep(0.3)
        return super().synthesize(text, voice)


async def test_review05_finding_15_the_latency_stops_at_the_first_chunk_not_the_end() -> None:
    elapsed = await first_audio(SlowSecondTts(), "Son las diez. Tiene una reunión.")

    assert elapsed is not None and elapsed < 200


@pytest.mark.parametrize(
    ("make_tts", "text"),
    [
        (lambda: FakeTts(fail_at_sentence=1), "Son las diez."),
        (SilentTts, "Son las diez."),
        (FakeTts, ""),
    ],
    ids=["tts_fails", "no_chunks", "empty_text"],
)
async def test_review05_finding_15_no_audio_is_a_failed_run_not_a_latency(make_tts, text) -> None:
    assert await first_audio(make_tts(), text) is None


async def test_review05_finding_15_a_stuck_synthesis_times_out() -> None:
    tts = StuckTts()
    try:
        assert await first_audio(tts, timeout_s=0.05) is None
    finally:
        tts.gate.set()


def test_review05_finding_15_failed_roundtrips_are_excluded_and_reported(
    cli: Registries, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TONY_EVALS", "1")
    samples = iter([100, None, 300, None, 200])
    monkeypatch.setattr(voice_cli, "measure_roundtrip", lambda *a: next(samples))

    result = runner.invoke(main.app, ["voice", "bench"])

    assert result.exit_code == 0, result.output
    row = next(line for line in result.stdout.splitlines() if line.startswith("roundtrip"))
    assert f"p50 {200:>6} ms" in row and f"p95 {300:>6} ms" in row
    assert "2/5 fallidas" in row


def test_review05_finding_15_all_failed_roundtrips_print_no_percentiles(
    cli: Registries, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TONY_EVALS", "1")
    monkeypatch.setattr(voice_cli, "measure_roundtrip", lambda *a: None)

    result = runner.invoke(main.app, ["voice", "bench"])

    assert result.exit_code == 0, result.output
    row = next(line for line in result.stdout.splitlines() if line.startswith("roundtrip"))
    assert "p50" not in row and "5/5 fallidas" in row


def test_review05_finding_15_a_clean_row_has_no_failure_note_nor_flag(
    cli: Registries, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TONY_EVALS", "1")
    monkeypatch.setattr(voice_cli, "measure_roundtrip", lambda *a: 1_500)

    result = runner.invoke(main.app, ["voice", "bench"])

    row = next(line for line in result.stdout.splitlines() if line.startswith("roundtrip"))
    assert row.endswith(f"p95 {1_500:>6} ms")
