## ADDED Requirements

### Requirement: Pre-image before file writes
For an allowed `filesystem.write_file` call the proxy SHALL, after `prepared` and before `dispatched`, ask the undo store to keep the file's previous content for that call id. On `succeeded` it SHALL record `sha256=<hex>` of the written content as the journal `detail`.

#### Scenario: Snapshot ordering
- **WHEN** an allowed write to an existing file runs
- **THEN** the pre-image exists before the tool is invoked

#### Scenario: Other tools
- **WHEN** any other tool runs
- **THEN** no pre-image is taken and `detail` is unchanged

### Requirement: Snapshot failure does not block calls
A pre-image failure SHALL NOT change the call's result or prevent execution; it SHALL be reported once per task as an `error` event, and the action stays `not undoable`.

#### Scenario: Unwritable undo directory
- **WHEN** the pre-image cannot be stored
- **THEN** the write still executes and one `error` event is published
