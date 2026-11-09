## ADDED Requirements

### Requirement: Proxy records observed tool results
The tool proxy SHALL record, per task, the text of each successful non-native tool result exactly as returned to the model, and expose the recorded texts for the task's evidence validation. It SHALL NOT record error results, `tony.*` results, or the output of calls it did not execute.

#### Scenario: Recorded text equals what the model saw
- **WHEN** a tool returns a result longer than the result cap
- **THEN** the recorded text is the capped text including its truncation marker

#### Scenario: Blocked call records nothing
- **WHEN** a call is denied by policy
- **THEN** nothing is recorded for it

### Requirement: Ask-user is not bound by the per-call timeout
The proxy SHALL NOT apply `tool_timeout_s` to `tony.ask_user`; the clarification wait is bounded by `confirm_timeout_s` and the task's cancellation instead.

#### Scenario: Slow answer
- **WHEN** the user answers a clarification after longer than `tool_timeout_s` but within `confirm_timeout_s`
- **THEN** the call returns the answer and is not reported as timed out
