# Spec Delta

## Purpose

Defines the per-task limits enforced around a worker run from the policy `limits`: repeated denials, per-agent step count, token alert, and how a task is cancelled and reported when a limit or a rejected confirmation stops it.

## ADDED Requirements

### Requirement: Task cancellation
A cancelled task SHALL stop the worker immediately, execute no further tool call, close all MCP connections, return a result with empty `resumen`, `datos: null` and `errores` containing the cancellation reason, and log `task_finished` with outcome `cancelled`. `tony run` SHALL exit non-zero for it.

#### Scenario: Cancelled run result
- **WHEN** a task is cancelled because a confirmation was rejected
- **THEN** the worker stops, its stdio MCP processes exit, the result's `errores` has one entry naming the tool and rule, the task log ends with `task_finished` outcome `cancelled` and `tony run` exits 1

### Requirement: Repeated denial cancels the task
Denials SHALL be counted per tool id within a task. When the same tool id is denied `limits.max_denied_retries` times, the task SHALL be cancelled with a reason naming the tool, the count and the rule.

#### Scenario: Third denial cancels the task
- **WHEN** in one task `shell.run` was already denied twice and Viernes calls a denied `shell.run` a third time
- **THEN** the third call is audited as `deny`, the task is cancelled and `errores` states `shell.run` was blocked 3 times

#### Scenario: Denials of different tools are independent
- **WHEN** `shell.run` and `foo.bar` are each denied twice in one task
- **THEN** the task is not cancelled

### Requirement: Step limit per agent
Each proxied call attempt SHALL count one step for the calling agent within the task. A call that would exceed `limits.max_steps_per_agent` MUST NOT be judged or executed and SHALL cancel the task with a reason naming the agent and the limit.

#### Scenario: Thirtieth step allowed
- **WHEN** Viernes makes its 30th call in a task with the default limit
- **THEN** the call is judged normally

#### Scenario: Thirty-first step cancels
- **WHEN** Viernes makes its 31st call in that task
- **THEN** the call is not executed, no audit line is written for it and the task is cancelled stating the 30-step limit

### Requirement: Token alert
When the task's total tokens (input plus output across all usage reports) exceed `limits.token_alert`, exactly one `token_alert` event SHALL be logged for that task with the total and the limit; the task SHALL NOT be cancelled.

#### Scenario: Above the threshold
- **WHEN** a task reports usages totalling 50001 tokens with the default limit
- **THEN** exactly one `token_alert` event with `total_tokens: 50001` and `limit: 50000` is logged and the task finishes normally

#### Scenario: At the threshold
- **WHEN** a task's usages total exactly 50000 tokens
- **THEN** no `token_alert` event is logged
