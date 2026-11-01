# task-log Specification

## Purpose
Defines the per-task JSONL audit log that records every significant event of a task run so it can be inspected after the fact.

## Requirements

### Requirement: One log file per task
Each task SHALL get a task id (UUID4 as 32 lowercase hex characters) and its events SHALL be appended to `logs/tasks/<task_id>.jsonl`, one JSON object per line, creating the folder when missing.

#### Scenario: Log file created
- **WHEN** a task with id `3f2c...` (32 hex chars) runs
- **THEN** `logs/tasks/3f2c....jsonl` exists and every line parses as a JSON object

### Requirement: Event envelope
Every event SHALL contain `ts` (ISO 8601 UTC timestamp with `Z` or `+00:00`), `task_id` and `type`, plus type-specific fields.

#### Scenario: Envelope fields present
- **WHEN** any event is written
- **THEN** it contains `ts` in UTC ISO 8601, the task's `task_id` and a `type`

### Requirement: Event types
A task run SHALL log at least: `task_started` (agent, task), `tool_call` (tool, args), `tool_result` (tool, ok flag, content), `token_usage` (input and output tokens), `task_finished` (outcome and result) and `error` (source, message).

#### Scenario: Ordered event sequence for a successful run
- **WHEN** Viernes completes a task calling two tools
- **THEN** the log starts with `task_started`, contains a `tool_call` followed by its `tool_result` for each call, contains at least one `token_usage`, and ends with `task_finished`

#### Scenario: Failed server logged
- **WHEN** a declared MCP server fails to connect
- **THEN** an `error` event names the server and the reason

### Requirement: Log contains no secrets
Task log events MUST NOT contain resolved secret values.

#### Scenario: Secret masked in log
- **WHEN** a tool call's args or result contain a resolved placeholder value
- **THEN** the corresponding log line contains `***` instead of the value
