# Spec Delta

## MODIFIED Requirements

### Requirement: Event types
A task run SHALL log at least: `task_started` (agent, task), `tool_call` (tool, args), `tool_result` (tool, ok flag, content), `token_usage` (input and output tokens), `token_alert` (total tokens and limit, when the alert threshold is exceeded), `task_finished` (outcome `ok`, `error`, `timeout` or `cancelled`, and result) and `error` (source, message).

#### Scenario: Ordered event sequence for a successful run
- **WHEN** Viernes completes a task calling two tools
- **THEN** the log starts with `task_started`, contains a `tool_call` followed by its `tool_result` for each call, contains at least one `token_usage`, and ends with `task_finished`

#### Scenario: Failed server logged
- **WHEN** a declared MCP server fails to connect
- **THEN** an `error` event names the server and the reason

#### Scenario: Cancelled task logged
- **WHEN** a task is cancelled by Edith or by a task limit
- **THEN** the log ends with `task_finished` whose outcome is `cancelled`

### Requirement: Log contains no secrets
Task log events MUST NOT contain secret values as defined by the configuration; non-secret values MUST be logged unchanged.

#### Scenario: Secret masked in log
- **WHEN** a tool call's args or result contain the value of a variable defined in `config/.env`
- **THEN** the corresponding log line contains `***` instead of the value

#### Scenario: Home path not masked in log
- **WHEN** a tool call's args contain the value of `${HOME}` taken only from the process environment
- **THEN** the corresponding log line contains the path unmasked
