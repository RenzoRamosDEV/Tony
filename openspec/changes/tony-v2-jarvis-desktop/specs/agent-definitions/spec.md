# Spec Delta

## MODIFIED Requirements

### Requirement: Bundled Viernes agent
The repository SHALL ship `agents/viernes/` with `role: worker`, `model: claude-sonnet`, Spanish persona with tone `cercano, ágil y pragmático; humor sutil solo en el resumen`, a `kokoro/<voice>` voice, a system prompt instructing it to solve the structured task with its tools, to answer with the structured result and never to address the user outside `resumen`, and a `tool.json` declaring the filesystem MCP server.

#### Scenario: Bundled agent validates
- **WHEN** the bundled `agents/viernes/` is loaded with the default configuration
- **THEN** loading succeeds and the agent's role is `worker` and its model alias is `claude-sonnet`

#### Scenario: Viernes persona
- **WHEN** the bundled `agents/viernes/agent.md` is loaded
- **THEN** its persona tone is `cercano, ágil y pragmático; humor sutil solo en el resumen`

## ADDED Requirements

### Requirement: Bundled Jarvis agent
The repository SHALL ship `agents/jarvis/` with `role: front`, `model: claude-haiku`, persona `language: es` and tone `formal, irónico, mayordomo británico; se dirige al usuario como «señor»`, voice `kokoro/em_alex`, a system prompt for conversing and delegating tasks, and a `tool.json` with no MCP servers and no native tools.

#### Scenario: Bundled Jarvis validates
- **WHEN** `agents/jarvis/` is loaded with the default configuration
- **THEN** loading succeeds with role `front`, model alias `claude-haiku`, voice `kokoro/em_alex`, no MCP servers and no native tools

#### Scenario: Jarvis prompt covers delegation
- **WHEN** the bundled Jarvis system prompt is read
- **THEN** it names the tools `delegate`, `remember` and `set_reply_mode` and instructs to address the user as «señor»
