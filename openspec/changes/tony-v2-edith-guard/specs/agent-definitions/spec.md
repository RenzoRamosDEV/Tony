# Spec Delta

## MODIFIED Requirements

### Requirement: Tool declaration schema
Each agent whose role is not `guard` SHALL have `agents/<name>/tool/tool.json` with `mcpServers` (map of server name to a stdio entry `{command, args?, env?}` or an HTTP entry `{url, headers?}`) and `native` (list of native tool names, default `[]`). Each server entry MUST define exactly one of `command` or `url`; unknown keys MUST be rejected.

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

## ADDED Requirements

### Requirement: Guard agent has no tools
An agent with role `guard` MUST NOT have a `tool/` folder; loading one that has it SHALL fail with an error naming `agents/<name>/tool/` and stating that a guard agent has no tools. A valid guard agent SHALL load with no MCP servers and no native tools.

#### Scenario: Guard with tool folder rejected
- **WHEN** `agents/edith/agent.md` declares `role: guard` and `agents/edith/tool/` exists
- **THEN** loading fails with an error naming `agents/edith/tool/`

#### Scenario: Guard without tool folder loads
- **WHEN** `agents/edith/agent.md` declares `role: guard` and there is no `agents/edith/tool/`
- **THEN** loading succeeds with no MCP servers and no native tools
