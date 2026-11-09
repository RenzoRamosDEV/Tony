## 1. Recorder and report
- [x] 1.1 Write failing tests: marks stored in order, null recorder is a no-op, concurrent marking, only names and timestamps stored, percentile values (1..20 -> p50 10.5, p95 19.05), cold/warm split, no p95 below 20 samples
- [x] 1.2 Implement `StageTimings`, `NullTimings` and the pure `summarise` report in `tony/core/voice/timing.py`

## 2. Loop lag
- [x] 2.1 Write failing tests for `LoopLagSampler` (blocked loop shows lag, stop leaves no task) using a short real block
- [x] 2.2 Implement `LoopLagSampler`

## 3. Pipeline wiring
- [x] 3.1 Write failing tests with fakes: listener, speaker and service record all eight marks in order when a recorder is passed and behave unchanged without one
- [x] 3.2 Add the optional recorder parameter to the listener, speaker and service and mark the stage boundaries

## 4. Benchmark
- [x] 4.1 Update `tests/voice/test_latency.py` to 20 runs, print the cold/warm report and loop lag, keep it non-asserting

## 5. Verification
- [x] 5.1 Run the full suite and mutation testing on the diff (>95 %, abort at 3 min)
