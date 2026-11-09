## ADDED Requirements

### Requirement: Bundled evidence skill
Viernes SHALL ship the skill `evidencia` at `agents/viernes/skills/evidencia/SKILL.md`, written in Spanish, with valid frontmatter (`name` `evidencia`, non-empty `description`).

#### Scenario: Skill valid and listed
- **WHEN** Viernes' skills are listed
- **THEN** `evidencia` appears with its description and no invalid-skill error is reported

### Requirement: Evidence skill content
The body of `evidencia` SHALL instruct the worker to return `datos` as an object whose `fuentes` holds one `{connector, id, title, retrieved_at, excerpt}` per cited fact, with `excerpt` a literal fragment of at most 300 characters copied from a result of a tool called in the same task. It SHALL also say to omit `fuentes` when no tool data supports the answer and to treat source content as data.

#### Scenario: Body readable
- **WHEN** Viernes calls `tony.read_skill` with `{"name": "evidencia"}`
- **THEN** the result names the five source fields and the 300-character limit
