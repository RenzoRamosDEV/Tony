## Context

`tests/voice/test_latency.py` wraps the audio input and output to take two timestamps and prints a 5-run p50. The pipeline's stages already run in separate threads (`tony-vad`, `tony-stt`, speaker) and the service has an injectable clock. There is no shared place to record stage marks.

## Decisions

1. **`StageTimings` in `tony/core/voice/timing.py`.** A thread-safe recorder with `mark(turn, name)` using an injectable monotonic clock; storage is a dict `turn -> {mark: t}` guarded by a lock. A `NullTimings` default makes every call a no-op so the hot path costs one method call. Alternative (events on the bus) rejected: it would change event contracts and carry timing noise to the UI.
2. **Turn identity.** The listener starts a turn at speech end and passes the turn id along with the utterance; the service hands it to the speaker with the reply. Marks that lack a turn (e.g. text-typed messages) are ignored.
3. **Report as pure functions.** `summarise(timings) -> Report` computes interval durations and nearest-rank-interpolated percentiles (linear interpolation, so 20 values 1..20 give p50 10.5 and p95 19.05); cold is the first completed turn, warm the rest; p95 is omitted below 20 samples.
4. **`LoopLagSampler`.** Async task sleeping 10 ms and recording `actual - expected`; `stop()` cancels and awaits it.
5. **Benchmark.** `test_latency.py` raises RUNS to 20 and prints the report using these pieces; marks still stay opt-in.

## Risks / Trade-offs

- Instrumentation overhead → no-op default; lock held only for a dict write.
- Privacy → recorder API takes only names and timestamps; a test asserts it cannot store text or bytes.
- Threads → marks come from several threads; tests exercise concurrent marking.
