# agent-definitions Specification

## Purpose
Defines how an agent is declared on disk (`agents/<name>/agent.md` and `agents/<name>/tool/tool.json`) and how Tony validates those files before any agent runs.

## Requirements

### Requirement: Agent file structure
An agent SHALL be declared by `agents/<name>/agent.md`, consisting of a YAML frontmatter block delimited by `---` lines followed by a Markdown body. The body SHALL be the agent's system prompt and MUST NOT be empty.

#### Scenario: Valid agent file is loaded
- **WHEN** `agents/viernes/agent.md` has valid frontmatter and a non-empty body
- **THEN** the loaded agent exposes the frontmatter fields and the body as its system prompt

#### Scenario: Missing frontmatter
- **WHEN** `agent.md` does not start with a `---` delimited YAML block
- **THEN** loading fails with an error naming the file

#### Scenario: Empty body
- **WHEN** the frontmatter is valid but the body is empty or whitespace only
- **THEN** loading fails with an error naming the file

### Requirement: Agent frontmatter schema
The frontmatter SHALL contain exactly these fields, all required: `name` (string equal to the agent folder name), `role` (`front`, `worker` or `guard`), `model` (a model alias), `persona` (`language`: string, `tone`: string) and `voice` (`tts`: string of the form `kokoro/<voice>`). Unknown fields at any level MUST be rejected.

#### Scenario: Name differs from folder
- **WHEN** `agents/viernes/agent.md` declares `name: friday`
- **THEN** loading fails with an error naming the file and the field `name`

#### Scenario: Invalid role
- **WHEN** the frontmatter declares `role: helper`
- **THEN** loading fails with an error naming the file and the field `role`

#### Scenario: Unknown field
- **WHEN** the frontmatter contains `max_steps: 20`
- **THEN** loading fails with an error naming the file and the field `max_steps`

#### Scenario: Missing required nested field
- **WHEN** `persona` omits `tone`
- **THEN** loading fails with an error naming the file and the field `persona.tone`

#### Scenario: Malformed voice
- **WHEN** `voice.tts` is `em_alex` (no `kokoro/` prefix) or `kokoro/` (empty voice)
- **THEN** loading fails with an error naming the file and the field `voice.tts`

#### Scenario: Model alias not configured
- **WHEN** `model` is `claude-opus` and that alias is not present in the configured `models`
- **THEN** loading fails with an error naming the file and the field `model`

### Requirement: Tool declaration schema
Each agent SHALL have `agents/<name>/tool/tool.json` with `mcpServers` (map of server name to a stdio entry `{command, args?, env?}` or an HTTP entry `{url, headers?}`) and `native` (list of native tool names, default `[]`). Each server entry MUST define exactly one of `command` or `url`; unknown keys MUST be rejected.

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
- **WHEN** the agent folder has no `tool/tool.json`
- **THEN** loading fails with an error naming the expected file path

### Requirement: Permissions are not declared in tool.json
The keys `allow` and `confirm` MUST be rejected at any depth of `tool.json`, with an error that names the file and the key and states that permissions belong to `agents/edith/policy.yaml`.

#### Scenario: Top-level confirm list
- **WHEN** `tool.json` contains `"confirm": ["filesystem.write_file"]`
- **THEN** loading fails with an error naming the file, the key `confirm`, and `agents/edith/policy.yaml`

#### Scenario: Nested allow key
- **WHEN** a server entry contains `"allow": ["read_file"]`
- **THEN** loading fails with an error naming the file, the key `mcpServers.<server>.allow`, and `agents/edith/policy.yaml`

### Requirement: Bundled Viernes agent
The repository SHALL ship `agents/viernes/` with `role: worker`, `model: claude-sonnet`, Spanish persona, a `kokoro/<voice>` voice, a system prompt instructing it to solve the structured task with its tools and to answer with the structured result, and a `tool.json` declaring the filesystem MCP server.

#### Scenario: Bundled agent validates
- **WHEN** the bundled `agents/viernes/` is loaded with the default configuration
- **THEN** loading succeeds and the agent's role is `worker` and its model alias is `claude-sonnet`
