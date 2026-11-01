# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Front control tools bypass the guard
The front control tools SHALL run without being submitted to the guard and without an audit line, because they only touch Tony's own memory or start a worker task whose tool calls are each judged. Every MCP and native tool call of the front agent SHALL still go through the guard like any proxied call.

#### Scenario: Delegate not audited
- **WHEN** Jarvis calls `delegate` and Viernes then calls `filesystem.read_file`
- **THEN** `logs/audit.jsonl` gains exactly one line, for `filesystem.read_file`

#### Scenario: Front agent MCP tool judged
- **WHEN** Jarvis's `tool.json` declares a server `clima` and Jarvis calls `clima.hoy`
- **THEN** the call is judged by Edith and audited with `agent: "jarvis"`
