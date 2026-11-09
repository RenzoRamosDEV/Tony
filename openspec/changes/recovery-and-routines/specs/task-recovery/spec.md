# Spec Delta

## Purpose

Lets the user see which delegated tasks ended without finishing, continue them safely as new tasks without repeating completed actions, and revert guarded file writes.

## ADDED Requirements

### Requirement: Recoverable task listing
`tony recover list` SHALL list worker tasks whose log ends with outcome `cancelled` or `timeout`, or has no `task_finished` event, showing task id, agent, outcome (`interrupted` when no end event), start time and request objective. Newest first, optional `--limit N` (default 20).

#### Scenario: Cancelled and timed-out tasks are listed
- **WHEN** logs hold one task ending `cancelled`, one ending `timeout` and one ending `ok`
- **THEN** only the first two are listed

#### Scenario: Task without end event
- **WHEN** a task log has `task_started` but no `task_finished` and was last written more than 15 minutes ago
- **THEN** it is listed with outcome `interrupted`

#### Scenario: Task possibly still running
- **WHEN** a task log has no `task_finished` and was written within the last 15 minutes
- **THEN** it is not listed

#### Scenario: Nothing to recover
- **WHEN** no task qualifies
- **THEN** the command prints `no tasks to recover` and exits 0

### Requirement: Succeeded actions in the listing
For each listed task `recover list` SHALL print its journal actions in state `succeeded` (call id, tool) and label each `undoable` or `not undoable`. An action SHALL be `undoable` only when it is a `filesystem.write_file` call with a stored pre-image.

#### Scenario: Write with pre-image
- **WHEN** a listed task has a succeeded `filesystem.write_file` with a stored pre-image
- **THEN** its line is labelled `undoable`

#### Scenario: Irreversible tool
- **WHEN** a listed task has a succeeded `shell.run` action
- **THEN** its line is labelled `not undoable`

#### Scenario: Resumed task hidden
- **WHEN** a later task was started by `recover resume` for a listed task
- **THEN** the original task is no longer listed

### Requirement: Resume as a new task
`tony recover resume TASK_ID` SHALL run the original agent and request again as a NEW task with a new task id under the normal guard and confirmations. The new request's `contexto` SHALL start with a note listing the actions already `succeeded` and stating they must not be repeated, followed by the original `contexto`.

#### Scenario: Resume with prior actions
- **WHEN** the original task had two succeeded actions and the user runs `recover resume` for it
- **THEN** a new task starts with a different id and its `contexto` begins with a note naming both actions

#### Scenario: Resume without prior actions
- **WHEN** the original task had no succeeded actions
- **THEN** the new request keeps the original `contexto` unchanged

#### Scenario: Guard still applies
- **WHEN** the resumed task calls a tool that requires confirmation
- **THEN** the confirmation is asked as for any task

### Requirement: Resume refusals
`recover resume` SHALL exit with the usage error code and print `tony: unknown task <id>` for an id with no task log, and `tony: task <id> is not recoverable` for a task that finished `ok` or `error`.

#### Scenario: Unknown task
- **WHEN** the id has no log file
- **THEN** the message is printed and no task starts

#### Scenario: Finished task
- **WHEN** the task ended `ok`
- **THEN** the not-recoverable message is printed and no task starts

### Requirement: Pre-image of file writes
Before a guarded `filesystem.write_file` executes, the system SHALL store the file's previous bytes under `memory/undo/<call_id>` when the file exists, is at most 1 MB and is valid UTF-8, and SHALL record `sha256=<hex>` of the content being written in the call's journal `detail`. A missing file or a larger or non-UTF-8 file stores nothing.

#### Scenario: Existing small file overwritten
- **WHEN** a 10-byte file is overwritten through the proxy
- **THEN** `memory/undo/<call_id>` holds the previous 10 bytes and the journal detail holds the sha256 of the new content

#### Scenario: File larger than 1 MB
- **WHEN** the existing file is 1 MB plus one byte
- **THEN** no pre-image is stored and the action is `not undoable`

#### Scenario: New file
- **WHEN** the file did not exist
- **THEN** no pre-image is stored

### Requirement: Undo of a file write
`tony recover undo CALL_ID` SHALL restore the stored content through a NEW guarded `filesystem.write_file` call, only when the file's current sha256 equals the recorded one. Otherwise it SHALL refuse with `file changed since the action` and write nothing.

#### Scenario: Unchanged file restored
- **WHEN** the file still holds the content the action wrote
- **THEN** the previous content is written back through the guard and the command exits 0

#### Scenario: File modified afterwards
- **WHEN** the file's current sha256 differs from the recorded one
- **THEN** the command prints `file changed since the action`, exits non-zero and writes nothing

#### Scenario: Undo is guarded
- **WHEN** the policy requires confirmation for `filesystem.write_file`
- **THEN** the undo asks for it and does not write when the user denies

### Requirement: Undo refusals
`recover undo` SHALL refuse with the usage error code for an unknown call id, an action not in state `succeeded`, and a tool other than `filesystem.write_file` (message `not undoable`), and when no pre-image is stored (message `no stored content for <call_id>`).

#### Scenario: Irreversible tool
- **WHEN** the call id belongs to a `shell.run` action
- **THEN** the command prints `not undoable` and runs nothing

#### Scenario: Unknown call
- **WHEN** the call id is not in the journal
- **THEN** a usage error is printed
