## MODIFIED Requirements

### Requirement: Tool declaration schema
Each agent whose role is not `guard` SHALL have `agents/<name>/tool/tool.json` with `mcpServers` (map of server name to a stdio entry `{command, args?, env?, isolation?}` or an HTTP entry `{url, headers?}`) and `native` (list of native tool names, default `[]`). Each server entry MUST define exactly one of `command` or `url`; unknown keys MUST be rejected. Server names MUST match `^[A-Za-z0-9]+([-_][A-Za-z0-9]+)*$`.

#### Scenario: Stdio and HTTP servers accepted
- **WHEN** `tool.json` declares `{"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/notas"]}, "remote": {"url": "https://example.test/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}}}`
- **THEN** loading succeeds with one stdio server, one HTTP server and `native` equal to `[]`

#### Scenario: Both command and url
- **WHEN** a server entry defines both `command` and `url`
- **THEN** loading fails with an error naming the file and the field `mcpServers.<server>`

#### Scenario: Neither command nor url
- **WHEN** a server entry defines neither `command` nor `url`
- **THEN** loading fails with an error naming the file and the field `mcpServers.<server>`

#### Scenario: Invalid JSON
- **WHEN** `tool.json` is not valid JSON
- **THEN** loading fails with an error naming the file

#### Scenario: Missing tool.json
- **WHEN** a `worker` or `front` agent folder has no `tool/tool.json`
- **THEN** loading fails with an error naming the expected file path

#### Scenario: Server name with a dot or double underscore
- **WHEN** `tool.json` declares a server named `my.server` or `my__server`
- **THEN** loading fails with an error naming the file and the field `mcpServers.<server>`

#### Scenario: Server name boundaries
- **WHEN** `tool.json` declares servers named `brave_search`, `gh-1` and `a`
- **THEN** loading succeeds, and a server named `-x`, `x-` or the empty string is rejected naming the file

#### Scenario: Stdio server with isolation accepted
- **WHEN** a stdio entry declares `"isolation": {"env_allow": ["GITHUB_TOKEN"]}`
- **THEN** loading succeeds and the entry keeps that allowlist

## ADDED Requirements

### Requirement: Isolation declaration shape
The optional `isolation` object of a stdio entry SHALL contain only `env_allow`, a list of variable names (letters, digits and `_`, not starting with a digit; default `[]`). An unknown key inside `isolation`, a malformed name, or `isolation` on an HTTP entry MUST be rejected with an error naming the file and the server field.

#### Scenario: HTTP entry with isolation
- **WHEN** an entry with `url` also declares `isolation`
- **THEN** loading fails with an error naming the file and the field `mcpServers.<server>`

#### Scenario: Unknown isolation key
- **WHEN** `isolation` contains a key other than `env_allow`
- **THEN** loading fails with an error naming the file and the field `mcpServers.<server>.isolation`

#### Scenario: Malformed variable name
- **WHEN** `env_allow` contains `1BAD` or `A=B`
- **THEN** loading fails with an error naming the file

#### Scenario: Empty isolation object
- **WHEN** a stdio entry declares `"isolation": {}`
- **THEN** loading succeeds with an empty allowlist and the server is still treated as isolated
