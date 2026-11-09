## ADDED Requirements

### Requirement: Clarification requested event
The core SHALL publish `clarification_requested` {request_id, task_id, agent, question, options} when a worker asks the user a question. It SHALL be distinct from `needs_confirmation` and, like every event, MUST NOT contain secret values.

#### Scenario: Round trip and masking
- **WHEN** the question contains the value of a variable defined in `config/.env`
- **THEN** the published event shows `***` instead of the value and round-trips through JSON unchanged

### Requirement: Answer clarification command
The command set SHALL include `answer_clarification` {request_id, answer}; any other or missing field SHALL be rejected as an invalid command that names the type and field but not the submitted answer.

#### Scenario: Valid command parsed
- **WHEN** `{"type": "answer_clarification", "request_id": "r1", "answer": "trabajo"}` is submitted
- **THEN** it is accepted

#### Scenario: Missing answer
- **WHEN** the command lacks `answer`
- **THEN** an `error` event names the command type and the field `answer`

### Requirement: Source lists in task results
Task `result` events SHALL carry sources, when any, only inside `result.datos.fuentes`; no new event type and no new top-level result field SHALL be added for them.

#### Scenario: Existing result shape
- **WHEN** a task with sources finishes
- **THEN** the `result` event keeps the fields of the existing task result event
