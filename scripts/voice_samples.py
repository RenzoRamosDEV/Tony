"""Listening pack of Jarvis voice candidates: one WAV per candidate in samples/voices/.

Usage: uv run python scripts/voice_samples.py   (needs `uv sync --extra voice`)

Prints a Markdown table (candidate, alias, first-chunk p50, approximate pitch, whether
how many words faster-whisper/base mishears, notes) for the README.
"""

from __future__ import annotations

import difflib
import gc
import statistics
import sys
import time
import warnings
import wave
from pathlib import Path

import numpy

from tony.apps.web.echo import normalize
from tony.core.voice.aliases import parse_alias
from tony.core.voice.engines import default_cpu_threads, load_tts
from tony.core.voice.engines.faster_whisper import FasterWhisperStt
from tony.core.voice.engines.piper import resample
from tony.core.voice.ports import INPUT_SAMPLE_RATE, OUTPUT_SAMPLE_RATE, Utterance

PARAGRAPH = (
    "Buenas tardes, señor. Los sistemas están en línea y la reunión de las cinco sigue en pie. "
    "Si me permite la sugerencia, quizá convenga revisar el informe antes; tiene un par de "
    "cifras optimistas."
)
FIRST_CLAUSE = "Enseguida lo reviso, señor."
REPETITIONS = 5
OUT_DIR = Path("samples/voices")
CANDIDATES = [
    ("piper_ald_medium_095", "piper/es_MX-ald-medium?speed=0.95", "por defecto"),
    ("piper_ald_medium_100", "piper/es_MX-ald-medium", "mismo timbre, ritmo normal"),
    ("piper_ald_x_low_095", "piper/es_MX-ald-x_low?speed=0.95", "modelo pequeño, más metálico"),
    ("piper_claude_high_095", "piper/es_MX-claude-high?speed=0.95", "tono más agudo"),
    (
        "kokoro_blend_alex_santa_es419",
        "kokoro/em_alex*0.6+em_santa*0.4?speed=0.94",
        "la más grave; alternativa documentada",
    ),
    ("kokoro_em_alex_es419", "kokoro/em_alex?speed=0.94", "masculina, seseo"),
    ("kokoro_em_santa_es419", "kokoro/em_santa?speed=0.94", "masculina, seseo"),
    ("kokoro_ef_dora_es", "kokoro/ef_dora?lang=es", "voz anterior (femenina, peninsular)"),
]


def pcm_of(tts, text: str) -> numpy.ndarray:
    chunks = list(tts.synthesize(text, ""))
    return numpy.frombuffer(b"".join(c.pcm16 for c in chunks), dtype=numpy.int16)


def first_chunk_ms(tts) -> int:
    samples = []
    for _ in range(REPETITIONS):
        started = time.perf_counter()
        next(iter(tts.synthesize(FIRST_CLAUSE, "")))
        samples.append((time.perf_counter() - started) * 1_000)
    return round(statistics.median(samples))


def pitch_hz(audio: numpy.ndarray) -> int:
    """Median autocorrelation pitch of the voiced 50 ms frames (60–300 Hz)."""
    signal = audio.astype(numpy.float32) / 32768.0
    frame = OUTPUT_SAMPLE_RATE // 20
    low, high = OUTPUT_SAMPLE_RATE // 300, OUTPUT_SAMPLE_RATE // 60
    estimates = []
    for start in range(0, len(signal) - frame, frame * 2):
        window = signal[start : start + frame]
        if numpy.abs(window).mean() < 0.02:
            continue
        correlation = numpy.correlate(window, window, "full")[frame - 1 :]
        estimates.append(OUTPUT_SAMPLE_RATE / (low + int(numpy.argmax(correlation[low:high]))))
    return round(statistics.median(estimates)) if estimates else 0


def write_wav(path: Path, audio: numpy.ndarray) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(OUTPUT_SAMPLE_RATE)
        file.writeframes(audio.tobytes())


def misheard_words(stt: FasterWhisperStt, audio: numpy.ndarray) -> int:
    """Words of the paragraph that faster-whisper/base does not hear back (0 = exact)."""
    speech = resample(numpy, audio / 32768.0, OUTPUT_SAMPLE_RATE, INPUT_SAMPLE_RATE)
    utterance = Utterance(speech.astype(numpy.float32).tobytes(), len(speech) // 16)
    heard = normalize(stt.transcribe(utterance, "es").text).split()
    expected = normalize(PARAGRAPH).split()
    matcher = difflib.SequenceMatcher(a=expected, b=heard, autojunk=False)
    return len(expected) - sum(block.size for block in matcher.get_matching_blocks())


def main() -> int:
    warnings.filterwarnings("ignore")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    threads = default_cpu_threads()
    stt = FasterWhisperStt("base", threads)
    rows = []
    for name, alias, note in CANDIDATES:
        tts = load_tts(parse_alias(alias), threads)
        pcm_of(tts, "Hola.")
        audio = pcm_of(tts, PARAGRAPH)
        path = OUT_DIR / f"{name}.wav"
        write_wav(path, audio)
        rows.append(
            (name, alias, first_chunk_ms(tts), pitch_hz(audio), misheard_words(stt, audio), note)
        )
        print(f"✓ {path}", file=sys.stderr, flush=True)
        del tts
        gc.collect()
    print("| Candidata | Alias para `voice.tts` | Primer fragmento p50 | f0 | Mal oídas | Notas |")
    print("|---|---|---|---|---|---|")
    for name, alias, first_ms, f0, misheard, note in rows:
        print(f"| `{name}.wav` | `{alias}` | {first_ms} ms | {f0} Hz | {misheard} | {note} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
