## ADDED Requirements

### Requirement: Opt-in stage timings
The voice pipeline SHALL accept an optional timing recorder. When none is given, the pipeline SHALL behave exactly as before and perform no timing work. When given, it SHALL record one monotonic timestamp for each of these marks per voice turn: speech end, capture close, speech-to-text start, speech-to-text end, first reply token, synthesis start, synthesis end and playback start. The recorder SHALL store only turn identifiers, mark names and timestamps, never audio or text.

#### Scenario: Recorder not provided
- **WHEN** a voice turn runs without a recorder
- **THEN** no timestamps are collected and the turn behaves as before

#### Scenario: All marks recorded
- **WHEN** a voice turn completes with a recorder
- **THEN** the recorder holds all eight marks for that turn in non-decreasing time order

### Requirement: Latency report
The report SHALL give, for each stage interval (speech end to capture close, capture close to transcript, transcript to first token, first token to playback start, and speech end to playback start), the p50 and p95 over the recorded turns, computed separately for the first turn after engines load (cold) and the following turns (warm). With fewer than 20 warm turns the report SHALL state the sample count and SHALL NOT claim a p95.

#### Scenario: Percentiles
- **WHEN** the report is computed over 20 warm turns whose end-to-end latencies are 1 s to 20 s in steps of 1 s
- **THEN** warm p50 is 10.5 s and warm p95 is 19.05 s

#### Scenario: Too few samples
- **WHEN** only 5 warm turns exist
- **THEN** the report shows the count 5 and no p95 value

### Requirement: Event loop lag
A lag sampler SHALL measure the delay of a periodic 10 ms timer on the core event loop and report the maximum and p95 lag in milliseconds while it runs. It SHALL stop and leave no task pending when asked.

#### Scenario: Blocked loop
- **WHEN** the loop is blocked for 200 ms while the sampler runs
- **THEN** the reported maximum lag is at least 190 ms

### Requirement: Benchmark reports without asserting
The voice latency benchmark SHALL run 20 turns and print the report; it SHALL NOT assert latency targets.

#### Scenario: Benchmark output
- **WHEN** the benchmark finishes
- **THEN** it prints cold and warm p50 and p95 per interval and the loop-lag figures
