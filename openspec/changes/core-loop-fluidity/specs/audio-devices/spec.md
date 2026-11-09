## ADDED Requirements

### Requirement: Device discovery does not block the core loop
Handling the `list_devices` command SHALL NOT run the blocking device query on the core event loop. Discovery SHALL run in a tracked background task and its result SHALL be published as the existing `audio_devices` event on the core loop. Event loop callbacks (token events, confirmations, cancellation) SHALL keep being served while discovery runs.

#### Scenario: Slow discovery during streaming
- **WHEN** the device query takes 5 s and a `list_devices` command arrives while a reply is streaming tokens
- **THEN** token events keep being published with no gap over 100 ms caused by discovery, and the `audio_devices` event is published when discovery completes

### Requirement: Concurrent discovery requests share one query
While a discovery is in flight, further `list_devices` commands SHALL join it instead of starting another query, and each SHALL result in one published `audio_devices` event with the same device lists.

#### Scenario: Two requests during one discovery
- **WHEN** two `list_devices` commands arrive while the first discovery is running
- **THEN** the device query runs once and two `audio_devices` events are published

### Requirement: Late discovery results are dropped
A discovery result that completes after the runtime has shut down SHALL NOT be published, and the background task SHALL be cancelled or awaited during shutdown.

#### Scenario: Shutdown during discovery
- **WHEN** the runtime shuts down while a discovery is in flight
- **THEN** no `audio_devices` event is published afterwards and no task is left pending
