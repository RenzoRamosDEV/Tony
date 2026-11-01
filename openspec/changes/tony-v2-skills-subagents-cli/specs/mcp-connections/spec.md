# Spec Delta

## MODIFIED Requirements

### Requirement: Tool identifiers
MCP tools SHALL be identified as `<server>.<tool>` and native tools as `tony.<name>`. Server names `tony` MUST be rejected to avoid collisions. Tony SHALL provide exactly the native tools `read_skill` and `run_subagent`, bound to the calling agent at each run.

#### Scenario: Native tool id
- **WHEN** Tony provides a native tool named `now` and an agent's `tool.json` declares `"native": ["now"]`
- **THEN** the catalog identifies that tool as `tony.now`

#### Scenario: Reserved server name
- **WHEN** `tool.json` declares a server named `tony`
- **THEN** loading fails with an error naming the file and the field `mcpServers.tony`

#### Scenario: Unknown native tool
- **WHEN** `native` lists a name Tony does not provide
- **THEN** loading fails with an error naming the file and the field `native`

#### Scenario: Production natives
- **WHEN** the production native tool names are listed
- **THEN** they are exactly `read_skill` and `run_subagent`

#### Scenario: Natives bound per agent
- **WHEN** Viernes and its subagent `resumidor` both declare `read_skill` and each calls it with a skill name of its own folder
- **THEN** each receives the body from its own `skills/` folder
