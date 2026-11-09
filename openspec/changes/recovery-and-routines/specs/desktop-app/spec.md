## ADDED Requirements

### Requirement: Core runtime runs the routine scheduler
The core runtime SHALL start the routine scheduler after a successful start and stop it on shutdown. A scheduler failure SHALL be published as an `error` event and SHALL NOT stop the runtime.

#### Scenario: Scheduler starts with the core
- **WHEN** the core starts without errors
- **THEN** due routines are executed while the window is open

#### Scenario: Scheduler failure
- **WHEN** a scheduler tick raises
- **THEN** an `error` event is published and the next tick still runs
