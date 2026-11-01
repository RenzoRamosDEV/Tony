# subagents Specification

## Purpose
Lets an agent hand a sub-problem to a specialised worker declared as a folder on disk, run inside the parent task through the `tony.run_subagent` native tool, with every subagent tool call judged and audited by the guard.

## Requirements

### Requirement: Subagent folder format
A subagent SHALL be `agents/<agent>/subagents/<name>/` with the same files and validation as an agent (`agent.md`, `tool/tool.json`, optional `skills/`). Its frontmatter `name` MUST equal the folder name, `role` MUST be `worker` and `description` (non-empty string) MUST be present. Its `tool.json` `native` MUST NOT include `run_subagent`.

#### Scenario: Valid subagent
- **WHEN** `agents/viernes/subagents/resumidor/` has an `agent.md` with `name: resumidor`, `role: worker`, `model: claude-sonnet`, a `description` and a body, and a valid `tool/tool.json`
- **THEN** the subagent `resumidor` is available to Viernes

#### Scenario: Non-worker role
- **WHEN** the subagent's `agent.md` declares `role: front`
- **THEN** the subagent is invalid with an error naming its `agent.md` and the field `role`

#### Scenario: Missing description
- **WHEN** the subagent's `agent.md` has no `description`
- **THEN** the subagent is invalid with an error naming its `agent.md` and the field `description`

#### Scenario: Nested subagents refused
- **WHEN** `agents/viernes/subagents/resumidor/tool/tool.json` declares `"native": ["run_subagent"]`
- **THEN** the subagent is invalid with an error naming that file and the field `native`

### Requirement: Subagents listed in the prompt
When an agent declares the native `run_subagent` and has at least one subagent folder with a valid `agent.md`, its system prompt SHALL end with a `## Subagentes` section containing one line `- <name>: <description>` per such subagent, sorted by name. The section SHALL be absent otherwise. Subagent folders SHALL be read from disk when each task or turn starts.

#### Scenario: Prompt lists subagents
- **WHEN** Viernes declares `run_subagent` and has the subagent `resumidor` with description `Resume textos largos`
- **THEN** its system prompt contains `## Subagentes` and `- resumidor: Resume textos largos`

### Requirement: Run subagent native tool
The native tool `tony.run_subagent` SHALL take `{name: string, tarea: {objetivo, contexto?, restricciones?}}`, run the calling agent's subagent with that exact name on the structured task with its own model alias, system prompt and `tool.json` MCP servers, and return its structured result `{resumen, datos, pasos, errores}` as JSON; the result SHALL be an error result when `errores` is not empty. The subagent's servers SHALL be closed when it returns.

#### Scenario: Subagent result returned
- **WHEN** Viernes calls `tony.run_subagent` with `{"name": "resumidor", "tarea": {"objetivo": "Resume a.md"}}` and the fake model scripts `resumidor` to call `filesystem.read_file` and answer a structured result
- **THEN** Viernes receives that result as JSON and no `resumidor` server process outlives the call

#### Scenario: Invalid task
- **WHEN** Viernes calls `tony.run_subagent` with `{"name": "resumidor", "tarea": {"objetivo": ""}}`
- **THEN** Viernes receives an error result naming `objetivo` and no subagent runs

### Requirement: Unknown or invalid subagent
`tony.run_subagent` SHALL only resolve names among the calling agent's subagent folders; an unknown name, including names with path separators or `..`, SHALL return the error result `subagent '<name>' not found; available: <comma-separated names or none>`, and an invalid subagent definition SHALL return an error result naming the file and field. Neither SHALL abort the parent task.

#### Scenario: Unknown subagent
- **WHEN** Viernes, having only the subagent `resumidor`, calls `tony.run_subagent` with name `traductor`
- **THEN** Viernes receives `subagent 'traductor' not found; available: resumidor` and the task continues

### Requirement: Subagent calls are judged and audited
Every tool call of a subagent SHALL go through the same guard as the parent with the envelope `agent` set to `<agent>/<name>`, be audited with that `agent`, and be counted by the parent task's supervisor under that agent name. The `tony.run_subagent` call itself SHALL be judged as a call of the parent agent.

#### Scenario: Subagent call audited
- **WHEN** Viernes runs the subagent `resumidor`, which calls `filesystem.read_file` under the shipped policy
- **THEN** `logs/audit.jsonl` gains a line with `agent: "viernes"`, `tool: "tony.run_subagent"`, `rule: "tony.read_skill/allow"` and a line with `agent: "viernes/resumidor"`, `tool: "filesystem.read_file"`

#### Scenario: Subagent denial cancels the parent task
- **WHEN** a subagent's calls are denied `limits.max_denied_retries` times for the same tool
- **THEN** the whole parent task is cancelled with the denial reason

### Requirement: Subagent runs inside the parent task
A subagent run SHALL share the parent task's id, task log, cancellation, task timeout and token accounting: its log events go to the parent's `logs/tasks/<task_id>.jsonl`, its token usage is logged and counted toward the token alert and the parent's `result` token totals, and cancelling or timing out the parent stops the subagent.

#### Scenario: Parent timeout stops the subagent
- **WHEN** the policy declares `limits: {task_timeout_s: 1}` and a subagent hangs
- **THEN** the parent task ends with outcome `timeout` after about 1 second and the subagent's server processes have exited

### Requirement: Subagent events as children of the parent task
A subagent's `tool_call` and `mcp_status` core events SHALL carry the parent's `task_id` and `agent` `<agent>/<name>`, and no separate `task_started` or task `result` event SHALL be published for it, so the Activity zone shows its calls under a child node of the parent task.

#### Scenario: Activity nesting
- **WHEN** a delegated Viernes task runs the subagent `resumidor`, which calls `filesystem.read_file`
- **THEN** a `tool_call` event with the parent `task_id` and `agent: "viernes/resumidor"` is published and the Activity presenter shows the call under the `resumidor` node of that task
