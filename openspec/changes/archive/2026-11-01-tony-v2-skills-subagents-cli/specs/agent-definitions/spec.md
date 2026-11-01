# Spec Delta

## MODIFIED Requirements

### Requirement: Agent frontmatter schema
The frontmatter SHALL contain these required fields: `name` (string equal to the agent folder name), `role` (`front`, `worker` or `guard`), `model` (a model alias), `persona` (`language`: string, `tone`: string) and `voice` (`tts`: string of the form `kokoro/<voice>`), plus the optional field `description` (non-empty string). Unknown fields at any level MUST be rejected.

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

#### Scenario: Optional description
- **WHEN** the frontmatter adds `description: Resume textos largos`
- **THEN** loading succeeds and the agent exposes that description

#### Scenario: Empty description
- **WHEN** the frontmatter declares `description: ""`
- **THEN** loading fails with an error naming the file and the field `description`

### Requirement: Tool declaration schema
Each agent whose role is not `guard` SHALL have `agents/<name>/tool/tool.json` with `mcpServers` (map of server name to a stdio entry `{command, args?, env?}` or an HTTP entry `{url, headers?}`) and `native` (list of native tool names, default `[]`). Each server entry MUST define exactly one of `command` or `url`; unknown keys MUST be rejected. Server names MUST match `^[A-Za-z0-9]+([-_][A-Za-z0-9]+)*$`.

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

### Requirement: Bundled Viernes agent
The repository SHALL ship `agents/viernes/` with `role: worker`, `model: claude-sonnet`, Spanish persona with tone `cercano, ágil y pragmático; humor sutil solo en el resumen`, a `kokoro/<voice>` voice, a system prompt instructing it to solve the structured task with its tools, to answer with the structured result and never to address the user outside `resumen`, and a `tool.json` declaring the filesystem MCP server and the natives `read_skill` and `run_subagent`.

#### Scenario: Bundled agent validates
- **WHEN** the bundled `agents/viernes/` is loaded with the default configuration
- **THEN** loading succeeds and the agent's role is `worker` and its model alias is `claude-sonnet`

#### Scenario: Viernes persona
- **WHEN** the bundled `agents/viernes/agent.md` is loaded
- **THEN** its persona tone is `cercano, ágil y pragmático; humor sutil solo en el resumen`

#### Scenario: Viernes natives
- **WHEN** the bundled `agents/viernes/tool/tool.json` is loaded
- **THEN** its `native` is `["read_skill", "run_subagent"]` and its catalog identifies them as `tony.read_skill` and `tony.run_subagent`
