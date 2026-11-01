# Spec Delta

## MODIFIED Requirements

### Requirement: Event types
A task run SHALL log at least: `task_started` (agent, task), `tool_call` (agent, tool, args), `tool_result` (agent, tool, ok flag, content), `token_usage` (input and output tokens), `token_alert` (total tokens and limit, when the alert threshold is exceeded), `task_finished` (outcome `ok`, `error`, `timeout` or `cancelled`, and result) and `error` (source, message). A subagent run SHALL be bracketed by `subagent_started` (agent `<agent>/<name>`, task) and `subagent_finished` (agent, outcome, result) in the parent task's log.

#### Scenario: Ordered event sequence for a successful run
- **WHEN** Viernes completes a task calling two tools
- **THEN** the log starts with `task_started`, contains a `tool_call` followed by its `tool_result` for each call, both with `agent: "viernes"`, contains at least one `token_usage`, and ends with `task_finished`

#### Scenario: Failed server logged
- **WHEN** a declared MCP server fails to connect
- **THEN** an `error` event names the server and the reason

#### Scenario: Cancelled task logged
- **WHEN** a task is cancelled by Edith or by a task limit
- **THEN** the log ends with `task_finished` whose outcome is `cancelled`

#### Scenario: Subagent events nested in the parent log
- **WHEN** Viernes calls `tony.run_subagent` for `resumidor`, which calls `filesystem.read_file`
- **THEN** the parent's log contains, in order, `tool_call` for `tony.run_subagent` with `agent: "viernes"`, `subagent_started` with `agent: "viernes/resumidor"`, `tool_call` and `tool_result` for `filesystem.read_file` with `agent: "viernes/resumidor"`, `subagent_finished` with outcome `ok`, and `tool_result` for `tony.run_subagent`; no other task log file is created
