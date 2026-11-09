## ADDED Requirements

### Requirement: Task origin and resume link
`task_started` SHALL include `origin` with value `routine` when the task was started by a scheduled routine, and `resumed_from` with the original task id when started by `tony recover resume`. Both fields MUST be absent otherwise.

#### Scenario: Routine task
- **WHEN** a routine starts a worker task
- **THEN** its `task_started` line has `"origin": "routine"`

#### Scenario: Ordinary task
- **WHEN** a task is started by `tony run`
- **THEN** its `task_started` line has neither field
