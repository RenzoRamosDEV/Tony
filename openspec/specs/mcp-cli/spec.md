# mcp-cli Specification

## Purpose
Lets the user add MCP servers to an agent's `tool.json` and check every declared server's state from the command line, without hand-editing JSON or touching Python.

## Requirements

### Requirement: MCP add command
`tony mcp add <name> <command-or-url> [--arg A]... [--header K=V]... [--env K=V]... --agent <agent>` SHALL add the server `<name>` to the agent's `tool.json` (`agents/<agent>/tool/tool.json`, or `agents/<agent>/subagents/<sub>/tool/tool.json` when `--agent` is `<agent>/<sub>`), keep every other key and server unchanged and in order, print `added <name> to <file>` and exit 0. `--agent` is required.

#### Scenario: Stdio server added
- **WHEN** the user runs `tony mcp add notas npx --arg -y --arg @modelcontextprotocol/server-filesystem --arg '${HOME}/notas' --env LOG=1 --agent viernes`
- **THEN** `agents/viernes/tool/tool.json` gains `"notas": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/notas"], "env": {"LOG": "1"}}`, the `filesystem` entry and `native` are unchanged, and the exit code is 0

#### Scenario: HTTP server added
- **WHEN** the user runs `tony mcp add remoto https://example.test/mcp --header 'Authorization=Bearer ${REMOTE_TOKEN}' --agent viernes`
- **THEN** the entry is `"remoto": {"url": "https://example.test/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}`

#### Scenario: Subagent target
- **WHEN** the user runs `tony mcp add notas npx --agent viernes/resumidor`
- **THEN** the entry is written to `agents/viernes/subagents/resumidor/tool/tool.json`

### Requirement: Transport chosen by target
A target starting with `http://` or `https://` SHALL create an HTTP entry `{url, headers?}`; any other target SHALL create a stdio entry `{command, args?, env?}`. `--header` with a stdio target, or `--arg`/`--env` with an HTTP target, SHALL exit non-zero with a usage error and leave the file unchanged. Empty `args`, `env` or `headers` SHALL be omitted.

#### Scenario: Header on a stdio target
- **WHEN** the user runs `tony mcp add x npx --header A=b --agent viernes`
- **THEN** the command exits non-zero with an error naming `--header` and the file is unchanged

#### Scenario: Plain command
- **WHEN** the user runs `tony mcp add reloj uvx --agent viernes`
- **THEN** the entry is exactly `"reloj": {"command": "uvx"}`

### Requirement: MCP add validation
`tony mcp add` SHALL exit non-zero, print an error on stderr and leave the file byte-identical when: the server name already exists in that file; the name violates the server name rules of the tool declaration schema; a `--header` or `--env` value has no `=` or an empty key; the agent folder or its `tool.json` does not exist; the agent is a guard; or the resulting `tool.json` fails validation.

#### Scenario: Duplicate refused
- **WHEN** the user runs `tony mcp add filesystem npx --agent viernes` and `filesystem` already exists
- **THEN** the command exits non-zero with an error naming `filesystem` and the file, and the file is byte-identical

#### Scenario: Reserved or malformed name
- **WHEN** the user runs `tony mcp add tony npx --agent viernes` or `tony mcp add a.b npx --agent viernes`
- **THEN** the command exits non-zero with an error naming the name and the file is unchanged

#### Scenario: Malformed pair
- **WHEN** the user runs `tony mcp add x npx --env TOKEN --agent viernes`
- **THEN** the command exits non-zero with a usage error naming `--env`

#### Scenario: Guard agent
- **WHEN** the user runs `tony mcp add x npx --agent edith`
- **THEN** the command exits non-zero stating that a guard agent has no tools and no `agents/edith/tool/` is created

### Requirement: Serialised atomic tool.json writes
`tony mcp add` SHALL hold an exclusive lock on `tool.json.lock` (next to the target `tool.json`) from reading the file until it is replaced, and SHALL replace the file atomically with UTF-8 JSON indented by 2 spaces and a trailing newline. If the lock is not obtained within 5 seconds the command SHALL exit non-zero naming the lock file, with the file unchanged.

#### Scenario: Concurrent adds both kept
- **WHEN** two `tony mcp add` processes add `a` and `b` to the same `tool.json` at the same time
- **THEN** both entries are present afterwards and the file is valid JSON

#### Scenario: Lock held elsewhere
- **WHEN** another process holds the lock on `agents/viernes/tool/tool.json.lock` for longer than 5 seconds
- **THEN** the command exits non-zero naming the lock file and `tool.json` is unchanged

### Requirement: Literal secret warning
When a `--header` or `--env` key matches `(?i)(token|key|secret|password|passwd|authorization|pin)` and its value contains no `${` placeholder, `tony mcp add` SHALL still write the entry and SHALL print on stderr a warning naming the key and recommending a `${VAR}` placeholder defined in `config/.env`. The command output MUST NOT contain header or env values.

#### Scenario: Literal token
- **WHEN** the user runs `tony mcp add gh npx --env GITHUB_TOKEN=s3cr3t --agent viernes`
- **THEN** the entry is written, stderr contains a warning naming `GITHUB_TOKEN` and `${`, and neither stdout nor stderr contains `s3cr3t`

### Requirement: MCP list command
`tony mcp list [--agent <agent>]` SHALL connect every MCP server declared by the given agent (or, without `--agent`, by every agent and subagent folder that has a `tool.json`, in path order) using the same connection rules as a task, and print a table with columns `agent`, `server`, `state` and `tools`, where `state` is `ok` or `error: <masked reason>` and `tools` the number of listed tools (`0` when down). All connections SHALL be closed before the command exits.

#### Scenario: One server up, one down
- **WHEN** Viernes declares the fake filesystem server and a server whose command does not exist, and the user runs `tony mcp list --agent viernes`
- **THEN** the filesystem row has `ok` and its tool count, the broken row has `error:` and the reason with `0` tools, and the exit code is 0

#### Scenario: Agent without servers
- **WHEN** the user runs `tony mcp list --agent jarvis` and Jarvis declares no servers
- **THEN** only the header is printed and the exit code is 0

### Requirement: MCP list errors
`tony mcp list` SHALL exit 0 whenever every listed `tool.json` is valid, whatever the servers' state. An unknown `--agent` SHALL exit non-zero naming the missing folder; an invalid `tool.json` SHALL print its error naming the file and field on stderr, still list the other agents' servers, and exit non-zero.

#### Scenario: Invalid tool.json among agents
- **WHEN** `agents/jarvis/tool/tool.json` is invalid JSON and the user runs `tony mcp list`
- **THEN** stderr names `agents/jarvis/tool/tool.json`, Viernes' servers are listed and the exit code is non-zero
