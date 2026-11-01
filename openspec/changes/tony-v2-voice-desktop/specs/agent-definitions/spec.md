# Spec Delta

## MODIFIED Requirements

### Requirement: Agent frontmatter schema
The frontmatter SHALL contain these required fields: `name` (string equal to the agent folder name), `role` (`front`, `worker` or `guard`), `model` (a model alias), `persona` (`language`: string, `tone`: string) and `voice` (`tts`: `kokoro/<voice>` or a comma-separated Kokoro voice blend `kokoro/<voice>,<voice>...`, each voice matching `[a-z]{2}_[a-z0-9]+`), plus the optional field `description` (non-empty string). Unknown fields at any level MUST be rejected.

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
- **WHEN** `voice.tts` is `em_alex` (no `kokoro/` prefix), `kokoro/` (empty voice), `kokoro/ef_dora,` (empty blend element) or `kokoro/ef dora` (space)
- **THEN** loading fails with an error naming the file and the field `voice.tts`

#### Scenario: Voice blend accepted
- **WHEN** `voice.tts` is `kokoro/ef_dora,bf_emma`
- **THEN** loading succeeds and the agent's voice is the blend of `ef_dora` and `bf_emma`

#### Scenario: Model alias not configured
- **WHEN** `model` is `claude-opus` and that alias is not present in the configured `models`
- **THEN** loading fails with an error naming the file and the field `model`

#### Scenario: Optional description
- **WHEN** the frontmatter adds `description: Resume textos largos`
- **THEN** loading succeeds and the agent exposes that description

#### Scenario: Empty description
- **WHEN** the frontmatter declares `description: ""`
- **THEN** loading fails with an error naming the file and the field `description`

### Requirement: Bundled Viernes agent
The repository SHALL ship `agents/viernes/` with `role: worker`, `model: claude-sonnet`, Spanish persona with tone `cercano, ágil y pragmático; humor sutil solo en el resumen`, voice `kokoro/ef_dora`, a system prompt instructing it to solve the structured task with its tools, to answer with the structured result and never to address the user outside `resumen`, and a `tool.json` declaring the filesystem MCP server and the natives `read_skill` and `run_subagent`.

#### Scenario: Bundled agent validates
- **WHEN** the bundled `agents/viernes/` is loaded with the default configuration
- **THEN** loading succeeds and the agent's role is `worker`, its model alias is `claude-sonnet` and its voice is `kokoro/ef_dora`

#### Scenario: Viernes persona
- **WHEN** the bundled `agents/viernes/agent.md` is loaded
- **THEN** its persona tone is `cercano, ágil y pragmático; humor sutil solo en el resumen`

#### Scenario: Viernes natives
- **WHEN** the bundled `agents/viernes/tool/tool.json` is loaded
- **THEN** its `native` is `["read_skill", "run_subagent"]` and its catalog identifies them as `tony.read_skill` and `tony.run_subagent`
