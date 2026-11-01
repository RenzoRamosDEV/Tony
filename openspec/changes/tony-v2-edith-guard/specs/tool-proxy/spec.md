# Spec Delta

## MODIFIED Requirements

### Requirement: Guard decision before execution
Every tool call SHALL be submitted to the guard before execution; the guard SHALL return a ruling with the policy `verdict` (`allow`, `confirm` or `deny`), the `rule` id and, for `confirm`, the `user_decision` (`allow`, `deny` or `timeout`). Only `allow`, or `confirm` with `user_decision` `allow`, executes the call; any other ruling MUST NOT invoke the real tool.

#### Scenario: Allowed call executes
- **WHEN** the guard returns verdict `allow`
- **THEN** the call is executed against the real tool and its result is returned to the agent

#### Scenario: Denied call does not execute
- **WHEN** the guard returns verdict `deny` with rule `shell.run/deny`
- **THEN** the real tool is not invoked and the agent receives the error result `{"error": "blocked_by_policy", "rule": "shell.run/deny"}`

#### Scenario: Confirmed call executes
- **WHEN** the guard returns verdict `confirm` with `user_decision` `allow`
- **THEN** the call is executed and its result is returned to the agent

#### Scenario: Confirm without confirmation support
- **WHEN** the guard returns verdict `confirm` and no confirmation channel is available
- **THEN** the call is treated as not confirmed (`user_decision` `deny`): not executed, the agent receives an error result naming the tool, and the task is cancelled

#### Scenario: Unconfirmed call cancels the task
- **WHEN** the guard returns verdict `confirm` with `user_decision` `deny` or `timeout`
- **THEN** the real tool is not invoked, the agent receives an error result naming the tool and the task is cancelled

### Requirement: Tool execution timeout
An allowed call SHALL run with the timeout `limits.tool_timeout_s` of the loaded policy (20 seconds by default), counted after any confirmation; on timeout the agent SHALL receive an error result naming the tool and the timeout, and the task SHALL continue.

#### Scenario: Tool exceeds timeout
- **WHEN** a tool does not respond within 20 seconds
- **THEN** the agent receives an error result stating that the tool timed out and the task is not aborted

#### Scenario: Confirmation wait not counted
- **WHEN** the user takes 30 seconds to confirm a call whose tool then answers in 1 second
- **THEN** the call succeeds and no timeout is reported

## REMOVED Requirements

### Requirement: Allow-all guard in this phase
**Reason**: Edith's deterministic policy guard replaces the placeholder allow-all guard; an always-allow guard would bypass policy, confirmation and audit.
**Migration**: `tony run` uses Edith with the policy at `agents/<guard>/policy.yaml`; tests that need a fixed decision use a recording guard test double.
