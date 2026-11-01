# tool-proxy Specification

## Purpose
Defines the single guarded, time-bounded path through which every agent tool call reaches a real MCP server or native tool, and the contract the guard must satisfy.

## Requirements

### Requirement: Tool call envelope
Every tool call SHALL be represented as a JSON-serializable `{task_id, agent, tool, args}` where `tool` is the tool id (`<server>.<tool>` or `tony.<name>`).

#### Scenario: Envelope round-trips as JSON
- **WHEN** Viernes calls `filesystem.read_file` with `{"path": "a.md"}` in task `abc`
- **THEN** the guard receives `{"task_id": "abc", "agent": "viernes", "tool": "filesystem.read_file", "args": {"path": "a.md"}}` and it serializes to and from JSON unchanged

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

### Requirement: Tool errors are returned, not raised
Tool failures (MCP error result, exception, unknown tool id, server down) SHALL be returned to the agent as error results; they MUST NOT abort the task.

#### Scenario: Tool reports error
- **WHEN** `filesystem.read_file` is called for a file that does not exist
- **THEN** the agent receives an error result with the server's message and can continue

#### Scenario: Call to a tool of a down server
- **WHEN** the agent calls a tool id that is not in its catalog
- **THEN** the agent receives an error result stating the tool is not available

### Requirement: Only proxied tools reach agents
Agents SHALL be offered only the proxied tools of their catalog and, for the front agent only, the front control tools `delegate`, `remember` and `set_reply_mode`. Built-in engine tools MUST be disabled and any tool name that is neither a proxied tool of the agent nor one of its control tools MUST be denied.

#### Scenario: Built-in tool requested
- **WHEN** the model requests the tool `Bash`
- **THEN** the request is denied and nothing is executed

#### Scenario: Proxied tool of another agent
- **WHEN** the model requests a proxied name not in the running agent's catalog
- **THEN** the request is denied

#### Scenario: Control tool requested by the worker
- **WHEN** Viernes, running a delegated task, requests `delegate`
- **THEN** the request is denied and no task is created

### Requirement: Front control tools bypass the guard
The front control tools SHALL run without being submitted to the guard and without an audit line, because they only touch Tony's own memory or start a worker task whose tool calls are each judged. Every MCP and native tool call of the front agent SHALL still go through the guard like any proxied call.

#### Scenario: Delegate not audited
- **WHEN** Jarvis calls `delegate` and Viernes then calls `filesystem.read_file`
- **THEN** `logs/audit.jsonl` gains exactly one line, for `filesystem.read_file`

#### Scenario: Front agent MCP tool judged
- **WHEN** Jarvis's `tool.json` declares a server `clima` and Jarvis calls `clima.hoy`
- **THEN** the call is judged by Edith and audited with `agent: "jarvis"`
