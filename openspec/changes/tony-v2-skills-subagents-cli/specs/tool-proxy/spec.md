# Spec Delta

## MODIFIED Requirements

### Requirement: Tool execution timeout
An allowed call SHALL run with the timeout `limits.tool_timeout_s` of the loaded policy (20 seconds by default), counted after any confirmation; on timeout the agent SHALL receive an error result naming the tool and the timeout, and the task SHALL continue. A `tony.run_subagent` call SHALL NOT be bounded by `limits.tool_timeout_s`; it is bounded by the parent task's timeout and cancellation.

#### Scenario: Tool exceeds timeout
- **WHEN** a tool does not respond within 20 seconds
- **THEN** the agent receives an error result stating that the tool timed out and the task is not aborted

#### Scenario: Confirmation wait not counted
- **WHEN** the user takes 30 seconds to confirm a call whose tool then answers in 1 second
- **THEN** the call succeeds and no timeout is reported

#### Scenario: Subagent longer than the tool timeout
- **WHEN** the policy declares `limits: {tool_timeout_s: 1, task_timeout_s: 10}` and a subagent run takes 2 seconds
- **THEN** the `tony.run_subagent` call returns the subagent's result and no tool timeout is reported
