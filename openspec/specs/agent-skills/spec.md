# agent-skills Specification

## Purpose
Lets an agent carry reusable instructions as skill folders on disk: only each skill's name and description go into the prompt, and the body is read on demand through the `tony.read_skill` native tool.

## Requirements

### Requirement: Skill folder format
A skill SHALL be `agents/<agent>/skills/<name>/SKILL.md` (or `agents/<agent>/subagents/<sub>/skills/<name>/SKILL.md` for a subagent): a `---` delimited YAML frontmatter with exactly `name` (equal to the folder name) and `description` (non-empty string), followed by a non-empty Markdown body. Unknown frontmatter fields MUST be rejected.

#### Scenario: Valid skill
- **WHEN** `agents/viernes/skills/resumir/SKILL.md` has `name: resumir`, `description: Resume notas en tres viñetas` and a body
- **THEN** the skill `resumir` is available to Viernes with that description

#### Scenario: Name differs from folder
- **WHEN** `agents/viernes/skills/resumir/SKILL.md` declares `name: resumen`
- **THEN** the skill is invalid with an error naming the file and the field `name`

#### Scenario: Unknown field
- **WHEN** the frontmatter contains `license: MIT`
- **THEN** the skill is invalid with an error naming the file and the field `license`

#### Scenario: Empty body
- **WHEN** the frontmatter is valid and the body is whitespace only
- **THEN** the skill is invalid with an error naming the file

### Requirement: Invalid skills are skipped
An invalid skill SHALL be left out of the agent's skills, and when the agent's skills are listed for a task an `error` event (source `skills`) naming the file and the reason SHALL be written to the task log and published; valid skills SHALL remain available and the task SHALL run.

#### Scenario: One broken skill among two
- **WHEN** Viernes has a valid skill `resumir` and a skill folder `roto` whose `SKILL.md` has no frontmatter, and a task starts
- **THEN** the prompt lists only `resumir`, an `error` event names `agents/viernes/skills/roto/SKILL.md` and the task runs

### Requirement: Skills listed in the prompt
When an agent declares the native `read_skill` and has at least one valid skill, its system prompt for a task or turn SHALL be its `agent.md` body followed by a `## Skills` section containing one line `- <name>: <description>` per skill, sorted by name, and no skill body. The section SHALL be absent when `read_skill` is not declared or no valid skill exists.

#### Scenario: Prompt lists name and description only
- **WHEN** Viernes declares `read_skill` and has the skill `resumir` with description `Resume notas en tres viñetas` and body `Paso 1...`
- **THEN** the system prompt contains `## Skills` and `- resumir: Resume notas en tres viñetas` and does not contain `Paso 1...`

#### Scenario: Native not declared
- **WHEN** an agent has skill folders but its `tool.json` `native` does not include `read_skill`
- **THEN** its system prompt has no `## Skills` section

### Requirement: Skills read from disk per task
The skills listed in the prompt SHALL be read from disk when each task or front-agent turn starts, so a skill folder added or edited between tasks is used by the next task without restart or code change.

#### Scenario: Skill added between tasks
- **WHEN** a task runs, then the folder `agents/viernes/skills/nueva/` with a valid `SKILL.md` is created, then another task runs
- **THEN** the second task's prompt lists `nueva` and the first did not

### Requirement: Read skill native tool
The native tool `tony.read_skill` SHALL take `{name: string}` and return the body of the calling agent's skill with that exact name. It SHALL only resolve names among the calling agent's valid skill folders; any other name, including names with path separators or `..`, SHALL return an error result `skill '<name>' not found; available: <comma-separated names or none>`.

#### Scenario: Body returned
- **WHEN** Viernes calls `tony.read_skill` with `{"name": "resumir"}`
- **THEN** the result is the body of `agents/viernes/skills/resumir/SKILL.md`

#### Scenario: Unknown skill
- **WHEN** Viernes, having skills `buscar` and `resumir`, calls `tony.read_skill` with `{"name": "traducir"}`
- **THEN** the agent receives the error result `skill 'traducir' not found; available: buscar, resumir` and the task continues

#### Scenario: Path traversal refused
- **WHEN** Viernes calls `tony.read_skill` with `{"name": "../../jarvis/skills/x"}`
- **THEN** the agent receives a not-found error result and no file outside Viernes' skill folders is read

#### Scenario: Skill read is judged and audited
- **WHEN** Viernes calls `tony.read_skill` under the shipped policy
- **THEN** the call is judged by Edith with verdict `allow` and rule `tony.read_skill/allow` and one audit line is written
