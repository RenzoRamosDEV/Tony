# Spec Delta

## MODIFIED Requirements

### Requirement: Agent field
`agent` SHALL be the calling agent's name, or `<agent>/<subagent>` when the call comes from a subagent.

#### Scenario: Worker call
- **WHEN** Viernes makes a call
- **THEN** `agent` is `viernes`

#### Scenario: Subagent call
- **WHEN** Viernes' subagent `resumidor` calls `filesystem.read_file`
- **THEN** the audit line has `agent: "viernes/resumidor"` and the same `task_id` as Viernes' own calls in that task
