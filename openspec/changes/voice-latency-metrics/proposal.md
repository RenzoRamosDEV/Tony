## Why

Voice latency is only measured from microphone closure to first audio, with a 5-run p50 in an optional benchmark. Endpointing delay, per-stage cost, tail latency (p95), cold versus warm behavior and event-loop lag are invisible, so future optimizations (such as streaming synthesis inside a sentence) cannot be justified with evidence.

## What Changes

- Add an optional, in-process stage timing recorder that marks speech end, capture close, speech-to-text start/end, first reply token, synthesis start/end and playback start for each voice turn. It records timestamps only, never audio or text.
- Add a latency report: per-stage durations with p50 and p95, split into cold (first turn after load) and warm turns, plus an event-loop lag sampler.
- Extend the voice latency benchmark to 20 runs and print the report; it still never asserts latency targets.
- Recorder is off by default: when not provided, voice components behave exactly as before. No event, config key or dependency is added or changed.

## Capabilities

### New Capabilities
- `voice-latency-metrics`: opt-in stage timings, percentile report and loop-lag measurement for the voice pipeline.

### Modified Capabilities
<!-- none: observable behavior of existing capabilities does not change -->

## Impact

- Code: new `tony/core/voice/timing.py`; optional parameter wiring in `tony/core/voice/listener.py`, `speaker.py`, `service.py`; `tests/voice/test_latency.py`.
- Events/config/dependencies: none.
