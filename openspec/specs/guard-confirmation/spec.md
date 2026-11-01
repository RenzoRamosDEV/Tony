# guard-confirmation Specification

## Purpose
Defines how Edith enforces each verdict on a proxied tool call: running it, blocking it with a structured error, or pausing the task to ask the user through the active confirmation channel with a formally worded question.

## Requirements

### Requirement: Every proxied call is judged by Edith
Every proxied tool call of a worker task, MCP (`<server>.<tool>`) and native (`tony.<name>`) alike, SHALL be judged by Edith against the loaded policy before execution. Edith SHALL be the guard used by `tony run`.

#### Scenario: Native tool judged
- **WHEN** Viernes calls the native tool `tony.read_skill` under the shipped policy
- **THEN** Edith judges it, the verdict is `allow` with rule `tony.read_skill/allow` and the tool runs

#### Scenario: Allowed read executes
- **WHEN** Viernes calls `filesystem.read_file` under the shipped policy
- **THEN** the call reaches the MCP and its result is returned to Viernes

### Requirement: Deny verdict result
A `deny` verdict MUST NOT execute the tool; the agent SHALL receive an error result whose text is the JSON `{"error": "blocked_by_policy", "rule": "<rule id>"}`.

#### Scenario: Dangerous shell command blocked
- **WHEN** Viernes calls `shell.run` with `command="sudo dnf update"` under the shipped policy
- **THEN** the MCP receives no call and Viernes receives `{"error": "blocked_by_policy", "rule": "shell.run/deny"}`

#### Scenario: Default deny never reaches the MCP
- **WHEN** a policy has `default: deny`, no rule matches `foo.bar` and Viernes calls `foo.bar`
- **THEN** the MCP receives no call and Viernes receives `{"error": "blocked_by_policy", "rule": "default"}`

### Requirement: Confirm verdict asks the user
A `confirm` verdict SHALL pause the call, word a question and ask it through the active confirmation channel, waiting up to `limits.confirm_timeout_s`. Only an explicit yes SHALL run the tool. A no, any other answer, a timeout or no available channel MUST NOT run the tool and SHALL cancel the whole task.

#### Scenario: Confirmed delete runs
- **WHEN** Viernes calls `filesystem.delete_file` and the user answers yes
- **THEN** the tool runs and its result is returned to Viernes

#### Scenario: Rejected delete cancels the task
- **WHEN** Viernes calls `filesystem.delete_file` and the user answers no
- **THEN** the tool is not executed, the task is cancelled and the result's `errores` states the user did not authorise `filesystem.delete_file` under rule `filesystem.delete*/confirm`

#### Scenario: Confirmation timeout
- **WHEN** a `confirm` for `filesystem.delete_file` gets no answer within `confirm_timeout_s` (60 s)
- **THEN** the tool is not executed, the task is cancelled, Viernes makes no further call and `errores` states the confirmation timed out

### Requirement: Confirmation question wording
The question SHALL have exactly the form `Acción: <qué>. Regla: <rule id>. ¿Autoriza?`. Edith's model (alias from its `agent.md`) SHALL fill `<qué>` from the tool id and masked args preview; if the model fails, takes more than 5 s or returns text not of that form, the deterministic `Acción: <tool id> <args preview>. Regla: <rule id>. ¿Autoriza?` SHALL be used. Unmasked args MUST NOT reach the model.

#### Scenario: Model wording used
- **WHEN** the wording model returns `Acción: borrar el archivo /home/renzo/notas/viejo.md. Regla: filesystem.delete*/confirm. ¿Autoriza?`
- **THEN** that exact text is asked

#### Scenario: Model too slow
- **WHEN** the wording model has not answered after 5 s
- **THEN** the question is `Acción: filesystem.delete_file {"path": "/home/renzo/notas/viejo.md"}. Regla: filesystem.delete*/confirm. ¿Autoriza?`

#### Scenario: Model breaks the template
- **WHEN** the wording model returns `¿Puedo borrar el archivo?` or raises an error
- **THEN** the deterministic question is asked

#### Scenario: Secret not sent to the model
- **WHEN** the args contain `{"token": "abc123"}`
- **THEN** the text given to the wording model contains `***` and not `abc123`

### Requirement: CLI confirmation channel
The CLI channel SHALL print the question on stderr and read one line from stdin. The answer trimmed and case-insensitive equal to `s`, `si`, `sí`, `y` or `yes` SHALL mean yes; any other line, end of input or the timeout SHALL mean no.

#### Scenario: Accepted answers
- **WHEN** the user types ` Sí ` or `YES` or `s`
- **THEN** the answer is yes

#### Scenario: Other answers
- **WHEN** the user types `vale`, an empty line, or input ends
- **THEN** the answer is no

#### Scenario: Question not on stdout
- **WHEN** `tony run` asks a confirmation
- **THEN** the question appears on stderr and stdout contains only the final JSON result
