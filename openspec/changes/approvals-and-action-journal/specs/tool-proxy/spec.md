## ADDED Requirements

### Requirement: Arguments checked before dispatch
The proxy SHALL compute the digest of a call's arguments before judging and again immediately before execution. When they differ, the tool MUST NOT run and the agent SHALL receive an error whose text is `tool <id> was not executed: not confirmed by the user (arguments changed)`.

#### Scenario: Arguments mutated while waiting
- **WHEN** the arguments are altered between the guard ruling and execution
- **THEN** the real tool is not invoked and the agent gets the arguments-changed error

#### Scenario: Unchanged arguments
- **WHEN** the arguments are identical at both points
- **THEN** the call executes normally

### Requirement: Journal writes around execution
For every call the guard lets run, the proxy SHALL record `prepared` after the ruling, `dispatched` right before invoking the tool, then `succeeded` for a normal result, `failed` for an error result or exception and `outcome_unknown` for a timeout. Denied, unconfirmed and arguments-changed calls SHALL NOT be journaled.

#### Scenario: Success path
- **WHEN** an allowed call returns normally
- **THEN** its row passes `prepared`, `dispatched`, `succeeded`

#### Scenario: Timeout
- **WHEN** execution exceeds the tool timeout
- **THEN** the row ends as `outcome_unknown`

#### Scenario: Denied call
- **WHEN** the guard denies a call
- **THEN** no journal row is created

### Requirement: Journal failure does not block calls
A journal write error SHALL NOT change the call's result or prevent execution; it SHALL be reported once per task as an `error` event.

#### Scenario: Unwritable journal
- **WHEN** the journal write raises
- **THEN** the call still executes and one `error` event is published
