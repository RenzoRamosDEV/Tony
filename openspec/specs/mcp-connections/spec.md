# mcp-connections Specification

## Purpose
Defines how Tony connects the MCP servers an agent declares, isolates failures between servers, and names the resulting tools.

## Requirements

### Requirement: Supported transports
Tony SHALL connect stdio servers (launched from `command`, `args`, `env`) and streamable-HTTP servers (`url`, `headers`) declared in an agent's `tool.json`, and list each server's tools.

#### Scenario: Stdio server tools listed
- **WHEN** an agent declares a stdio filesystem server exposing `list_directory` and `read_file`
- **THEN** the agent's tool catalog contains `filesystem.list_directory` and `filesystem.read_file`

#### Scenario: HTTP server tools listed
- **WHEN** an agent declares a streamable-HTTP server named `remote` exposing `ping`
- **THEN** the agent's tool catalog contains `remote.ping`

### Requirement: Connect timeout per server
Each server connection, including its initialization handshake and tool listing, SHALL be bounded by a 10 second timeout, applied independently per server.

#### Scenario: Server hangs on connect
- **WHEN** a server does not finish initializing within 10 seconds
- **THEN** that server is marked down with a timeout reason and the remaining servers are unaffected

### Requirement: Failure isolation
A server that fails to connect SHALL be marked down, logged to the task log as an `error` event and to stderr with the server name and reason, and skipped; the tools of the other servers SHALL remain available and the task SHALL continue.

#### Scenario: MCP down at start
- **WHEN** `tool.json` declares a stdio server whose command does not exist, alongside a working filesystem server
- **THEN** the broken server is marked down, an `error` event naming it is written to the task log and stderr, the filesystem tools are callable, and the run continues to completion

### Requirement: Tool identifiers
MCP tools SHALL be identified as `<server>.<tool>` and native tools as `tony.<name>`. Server names `tony` MUST be rejected to avoid collisions.

#### Scenario: Native tool id
- **WHEN** Tony provides a native tool named `now` and an agent's `tool.json` declares `"native": ["now"]`
- **THEN** the catalog identifies that tool as `tony.now`

#### Scenario: Reserved server name
- **WHEN** `tool.json` declares a server named `tony`
- **THEN** loading fails with an error naming the file and the field `mcpServers.tony`

#### Scenario: Unknown native tool
- **WHEN** `native` lists a name Tony does not provide
- **THEN** loading fails with an error naming the file and the field `native`

### Requirement: Connections are closed
All server connections opened for a task SHALL be closed when the task finishes, fails or times out, and no stdio server process SHALL outlive the task.

#### Scenario: Process cleanup after task
- **WHEN** a task using a stdio server finishes
- **THEN** the server process has exited
