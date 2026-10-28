"""`tony voice warmup` and `tony voice bench`: load the local engines and measure them."""

from __future__ import annotations

import asyncio
import math
import os
import time
from array import array
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from tony.apps.cli.voice_stream_bench import (
    QUESTION as SPOKEN_QUESTION,
)
from tony.apps.cli.voice_stream_bench import (
    StreamSample,
    measure_stream_roundtrip,
    spoken_utterance,
)
from tony.core.channels.bootstrap import RuntimeOptions, build_chat_runtime
from tony.core.channels.ports import AssistantReply, ChannelMessage
from tony.core.config import ConfigError, VoiceSettings, load_settings
from tony.core.runner import EventSink
from tony.core.voice.aliases import alias_problem
from tony.core.voice.engines import EngineRegistry
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.pipeline import SpeechPipeline
from tony.core.voice.ports import INPUT_SAMPLE_RATE, AudioChunk, Tts, Utterance, VoiceConfigError

DEFAULT_CONFIG = Path("config/tony.yaml")
DEFAULT_AGENTS_DIR = Path("agents")
EXTRA_MISSING = "Falta el extra de voz: instala con `uv sync --extra voice`."
REPETITIONS = 5
TARGET_MS = 2_500
TARGET_ROW = "roundtrip_stream"
NOT_MET = "objetivo no alcanzado (p50 > 2500 ms)"
BENCH_SENTENCE = "Buenos días señor, tiene tres reuniones hoy y la primera empieza pronto."
FIRST_CLAUSE = "Enseguida lo reviso, señor."
ROUNDTRIP_QUESTION = "¿qué hora es?"
STT_SAMPLE_S = 3
FIRST_AUDIO_TIMEOUT_S = 60.0

app = typer.Typer(
    help="Voz local: descarga y carga los modelos (warmup) o mide su latencia (bench).",
    no_args_is_help=True,
)
ConfigOption = Annotated[
    Path, typer.Option("--config", help="Ruta del fichero de configuración de Tony.")
]
AgentsDirOption = Annotated[
    Path, typer.Option("--agents-dir", help="Directorio que contiene las carpetas de agentes.")
]


def default_registry_factory(settings: VoiceSettings) -> EngineRegistry:
    return EngineRegistry(settings)


# Module attributes so the tests inject doubles.
registry_factory: Callable[[VoiceSettings], EngineRegistry] = default_registry_factory


def percentiles(samples: list[int]) -> tuple[int, int]:
    """Nearest-rank p50 and p95 of a non-empty sample."""
    ordered = sorted(samples)
    rank = lambda p: ordered[max(0, math.ceil(p * len(ordered)) - 1)]  # noqa: E731
    return rank(0.5), rank(0.95)


def format_ms(ms: int) -> str:
    return f"{ms:,}".replace(",", " ")


def synthetic_speech(seconds: int = STT_SAMPLE_S) -> Utterance:
    """A 220 Hz tone breathing at 4 Hz: no human voice, same energy profile as the fixtures."""
    count = INPUT_SAMPLE_RATE * seconds
    pcm = array(
        "f",
        (
            0.5
            * (0.75 + 0.25 * math.sin(2 * math.pi * 4 * i / INPUT_SAMPLE_RATE))
            * math.sin(2 * math.pi * 220 * i / INPUT_SAMPLE_RATE)
            for i in range(count)
        ),
    )
    return Utterance(pcm=pcm.tobytes(), duration_ms=seconds * 1_000)


def _load(config: Path) -> tuple[EngineRegistry, VoiceSettings]:
    try:
        settings = load_settings(config)
    except ConfigError as exc:
        typer.echo(f"Configuración inválida en {config}: {exc}", err=True)
        raise typer.Exit(2) from None
    try:
        for key, alias in (("voice.stt", settings.voice.stt), ("voice.tts", settings.voice.tts)):
            problem = alias_problem(key, alias)
            if problem is not None:
                raise VoiceConfigError(problem)
        return registry_factory(settings.voice), settings.voice
    except ImportError:
        typer.echo(EXTRA_MISSING, err=True)
        raise typer.Exit(2) from None
    except VoiceConfigError as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(1) from None


def _warmup(registry: EngineRegistry) -> dict[str, int]:
    try:
        return registry.warmup()
    except ImportError:
        typer.echo(EXTRA_MISSING, err=True)
        raise typer.Exit(2) from None
    except Exception as exc:  # noqa: BLE001 - any engine failure is the diagnosis itself
        typer.echo(f"✗ no se pudo cargar un motor: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command(help="Descarga los modelos que falten y carga los tres motores (VAD, STT, TTS).")
def warmup(config: ConfigOption = DEFAULT_CONFIG) -> None:
    registry, _ = _load(config)
    for name, ms in _warmup(registry).items():
        typer.echo(f"✓ {name} {format_ms(ms)} ms")


@app.command(
    help="Mide p50/p95 de la carga, el STT (3 s y una pregunta hablada) y el TTS (12 palabras "
    "y primer fragmento); con TONY_EVALS=1 también el primer token del modelo y la ida y "
    "vuelta, completa y en streaming, desde el fin del habla hasta el primer audio."
)
def bench(
    config: ConfigOption = DEFAULT_CONFIG, agents_dir: AgentsDirOption = DEFAULT_AGENTS_DIR
) -> None:
    registry, voice = _load(config)
    timings = _warmup(registry)
    stt = registry.get_stt(voice.stt)
    tts = registry.get_tts(voice.tts)
    sample = synthetic_speech()
    question = spoken_utterance(tts, registry.tts_voice, SPOKEN_QUESTION)
    rows: dict[str, list[int | None]] = {
        "load": [sum(timings.values())],
        "stt_3s": [_timed(lambda: stt.transcribe(sample, "es")) for _ in range(REPETITIONS)],
        "stt_utt": [_timed(lambda: stt.transcribe(question, "es")) for _ in range(REPETITIONS)],
        "tts_12w": [
            _timed(lambda: list(tts.synthesize(BENCH_SENTENCE, registry.tts_voice)))
            for _ in range(REPETITIONS)
        ],
        "tts_first": [
            _timed(lambda: next(iter(tts.synthesize(FIRST_CLAUSE, registry.tts_voice)), None))
            for _ in range(REPETITIONS)
        ],
    }
    streams: list[StreamSample | None] = []
    if os.environ.get("TONY_EVALS") == "1":
        rows["roundtrip"] = [
            measure_roundtrip(config, agents_dir, registry) for _ in range(REPETITIONS)
        ]
        streams = [measure_stream(config, agents_dir, registry) for _ in range(REPETITIONS)]
        rows["ttft"] = [None if s is None else s.ttft_ms for s in streams]
        rows[TARGET_ROW] = [None if s is None else s.total_ms for s in streams]
    for name, samples in rows.items():
        typer.echo(bench_row(name, samples))
    if streams:
        typer.echo(breakdown_row(streams))


def bench_row(name: str, samples: list[int | None]) -> str:
    """p50/p95 of the successful runs; failed runs (None) are only counted."""
    measured = [ms for ms in samples if ms is not None]
    failed = len(samples) - len(measured)
    note = f"  ({failed}/{len(samples)} fallidas)" if failed else ""
    if not measured:
        return f"{name:<10} sin muestras válidas{note}"
    p50, p95 = percentiles(measured)
    flag = f"  {NOT_MET}" if name == TARGET_ROW and p50 > TARGET_MS else ""
    return f"{name:<10} p50 {p50:>6} ms  p95 {p95:>6} ms{flag}{note}"


def breakdown_row(streams: list[StreamSample | None]) -> str:
    """Where the time of the median streaming roundtrip went."""
    measured = sorted((s for s in streams if s is not None), key=lambda s: s.total_ms)
    if not measured:
        return "desglose   sin muestras válidas"
    median = measured[max(0, math.ceil(0.5 * len(measured)) - 1)]
    return (
        f"desglose   endpoint {median.endpoint_ms} ms · stt {median.stt_ms} ms · "
        f"ttft {median.ttft_ms} ms · tts_first {median.tts_first_ms} ms"
    )


def _timed(fn: Callable[[], object]) -> int:
    started = time.perf_counter()
    fn()
    return int((time.perf_counter() - started) * 1_000)


class _ReplyChannel:
    def __init__(self) -> None:
        self.reply: AssistantReply | None = None

    async def send(self, message: ChannelMessage) -> None:
        if isinstance(message, AssistantReply):
            self.reply = message


class _FirstChunk:
    """Resolves `first_audio` only on a real chunk; any other ending leaves it unset."""

    def __init__(self) -> None:
        self.first_audio = asyncio.Event()

    async def start(self) -> None:
        return None

    async def chunk(self, seq: int, sentence_index: int, audio: AudioChunk) -> None:
        self.first_audio.set()

    async def end(self) -> None:
        return None

    async def cancelled(self) -> None:
        return None

    async def failed(self, error: str) -> None:
        return None


async def time_to_first_audio(
    tts_loader: Callable[[], Tts],
    executor: VoiceExecutor,
    voice: str,
    text: str,
    events: EventSink,
    started: float,
    timeout_s: float = FIRST_AUDIO_TIMEOUT_S,
) -> int | None:
    """Milliseconds from `started` to the first chunk, or None when no audio came in time."""
    sink = _FirstChunk()
    pipeline = SpeechPipeline(tts_loader, executor, voice, sink, events)
    pipeline.feed(text)
    finishing = asyncio.ensure_future(pipeline.finish())
    first_audio = asyncio.ensure_future(sink.first_audio.wait())
    await asyncio.wait(
        {finishing, first_audio}, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED
    )
    elapsed = int((time.perf_counter() - started) * 1_000)
    first_audio.cancel()
    if not sink.first_audio.is_set():
        await pipeline.cancel()
        await asyncio.gather(finishing, return_exceptions=True)
        return None
    await finishing
    return elapsed


def default_measure_roundtrip(
    config: Path, agents_dir: Path, registry: EngineRegistry
) -> int | None:
    """Milliseconds from a ready transcript to the first synthesized chunk, with the real model."""
    return asyncio.run(_roundtrip(config, agents_dir, registry))


measure_roundtrip: Callable[[Path, Path, EngineRegistry], int | None] = default_measure_roundtrip
measure_stream: Callable[[Path, Path, EngineRegistry], StreamSample | None] = (
    measure_stream_roundtrip
)


async def _roundtrip(config: Path, agents_dir: Path, registry: EngineRegistry) -> int | None:
    from tony.core.mcp import ConfirmGate  # noqa: F401 - type only, keeps the import local

    channel = _ReplyChannel()
    runtime = await build_chat_runtime(
        RuntimeOptions(config_path=config, agents_dir=agents_dir),
        gate_factory=lambda settings, front: _AutoGate(),
    )
    executor = VoiceExecutor()
    try:
        session = await runtime.open_session(
            runtime.memory.conversations.start_conversation("bench"), channel
        )
        started = time.perf_counter()
        reply = await session.handle(ROUNDTRIP_QUESTION, "audio")
        if reply is None:
            return None
        return await time_to_first_audio(
            lambda: registry.get_tts(registry.tts_alias),
            executor,
            registry.tts_voice,
            reply.speech_text or reply.display_text,
            runtime,
            started,
        )
    finally:
        executor.close()
        await runtime.aclose()


class _AutoGate:
    async def confirm(self, request: object) -> bool:
        return False
