## ADDED Requirements

### Requirement: Action record
The journal SHALL store one row per journaled call in `memory/actions.sqlite`, table `actions`, with `call_id` (uuid4), `task_id`, `agent`, `tool`, `args_digest`, `state`, `created_at`, `updated_at` and `detail`. It SHALL NOT store arguments, only their digest.

#### Scenario: Row content
- **WHEN** an allowed call is prepared
- **THEN** a row exists with a fresh `call_id`, the task, agent and tool, the args sha256 and state `prepared`

### Requirement: Call states
`state` SHALL be one of `prepared`, `dispatched`, `succeeded`, `failed`, `outcome_unknown`, and `updated_at` SHALL change on every transition.

#### Scenario: Failure
- **WHEN** a dispatched call returns an error result
- **THEN** its state is `failed`

### Requirement: Masked bounded detail
`detail` SHALL be a short reason, masked with the secret masker and at most 200 characters, empty when there is none.

#### Scenario: Secret in error
- **WHEN** a failure message contains a known secret
- **THEN** `detail` shows the mask and is at most 200 characters

### Requirement: Interrupted calls recovered at startup
At startup of a host that runs tools, every row in `dispatched` whose `updated_at` precedes the process start SHALL become `outcome_unknown` with a detail stating the interruption. Rows in other states are untouched. Read-only inspection commands MUST NOT run this recovery.

#### Scenario: Crash recovery
- **WHEN** the process restarts and a `dispatched` row from the previous run exists
- **THEN** it becomes `outcome_unknown`

#### Scenario: Prepared row kept
- **WHEN** a `prepared` row from a previous run exists
- **THEN** it stays `prepared`

### Requirement: Never replayed automatically
The core MUST NOT re-execute a journaled call on its own for any state, including `outcome_unknown`.

#### Scenario: Restart
- **WHEN** the process restarts with `outcome_unknown` rows
- **THEN** no tool is invoked because of them

### Requirement: Actions list command
`tony actions list [--state STATE] [--limit N]` SHALL print newest-first rows (call id, time, state, agent, tool), default limit 20, filtered by state when given. An unknown state or a non-positive limit SHALL exit 2 with an error.

#### Scenario: Filter
- **WHEN** `tony actions list --state outcome_unknown` runs with two such rows among five
- **THEN** only those two are printed

#### Scenario: Bad state
- **WHEN** `--state bogus` is given
- **THEN** exit code 2 and an error naming the valid states

#### Scenario: Empty
- **WHEN** the journal has no rows or does not exist
- **THEN** a no-actions message is printed and the exit code is 0

### Requirement: Actions show command
`tony actions show CALL_ID` SHALL print every column of that row. An unknown id SHALL exit 2.

#### Scenario: Known id
- **WHEN** the id exists
- **THEN** the call's fields, state and detail are printed

#### Scenario: Unknown id
- **WHEN** the id does not exist
- **THEN** exit code 2 with an error naming the id

### Requirement: Unknown outcomes only reported
`outcome_unknown` rows SHALL be reported as such; no reconciliation with connectors is performed.

#### Scenario: Reported
- **WHEN** a row is `outcome_unknown`
- **THEN** list and show print that state and nothing claims success or failure
