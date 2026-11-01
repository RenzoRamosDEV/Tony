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
Every tool call SHALL be submitted to the guard before execution; the guard SHALL return `allow`, `confirm` or `deny`. Only `allow` executes the call; `deny` MUST return an error result to the agent without executing.

#### Scenario: Allowed call executes
- **WHEN** the guard returns `allow`
- **THEN** the call is executed against the real tool and its result is returned to the agent

#### Scenario: Denied call does not execute
- **WHEN** the guard returns `deny`
- **THEN** the real tool is not invoked and the agent receives an error result naming the tool

#### Scenario: Confirm without confirmation support
- **WHEN** the guard returns `confirm` in this phase (no confirmation channel exists)
- **THEN** the call is treated as not confirmed: not executed, and the agent receives an error result naming the tool

### Requirement: Allow-all guard in this phase
The only guard provided in this phase SHALL always return `allow`.

#### Scenario: Any call allowed
- **WHEN** any tool call is submitted to the allow-all guard
- **THEN** the decision is `allow`

### Requirement: Tool execution timeout
An allowed call SHALL run with a 20 second timeout; on timeout the agent SHALL receive an error result naming the tool and the timeout, and the task SHALL continue.

#### Scenario: Tool exceeds timeout
- **WHEN** a tool does not respond within 20 seconds
- **THEN** the agent receives an error result stating that the tool timed out and the task is not aborted

### Requirement: Tool errors are returned, not raised
Tool failures (MCP error result, exception, unknown tool id, server down) SHALL be returned to the agent as error results; they MUST NOT abort the task.

#### Scenario: Tool reports error
- **WHEN** `filesystem.read_file` is called for a file that does not exist
- **THEN** the agent receives an error result with the server's message and can continue

#### Scenario: Call to a tool of a down server
- **WHEN** the agent calls a tool id that is not in its catalog
- **THEN** the agent receives an error result stating the tool is not available

### Requirement: Only proxied tools reach agents
Agents SHALL be offered only the proxied tools of their catalog. Built-in engine tools MUST be disabled and any tool name that is not a proxied tool of the agent MUST be denied.

#### Scenario: Built-in tool requested
- **WHEN** the model requests the tool `Bash`
- **THEN** the request is denied and nothing is executed

#### Scenario: Proxied tool of another agent
- **WHEN** the model requests a proxied name not in the running agent's catalog
- **THEN** the request is denied
