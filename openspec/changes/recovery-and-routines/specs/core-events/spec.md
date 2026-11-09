## ADDED Requirements

### Requirement: Routine task origin event field
`task_started` SHALL carry `origin: "routine"` for tasks started by a routine and no `origin` field otherwise. The turn `origin` values (`text`, `voice`) and the `send_message` validation SHALL NOT change; a UI command MUST NOT be able to submit `routine`.

#### Scenario: Routine task event
- **WHEN** a routine starts a task
- **THEN** the `task_started` event has `origin: "routine"`

#### Scenario: Command cannot claim routine
- **WHEN** a `send_message` command has `origin: "routine"`
- **THEN** it is rejected as an invalid command
