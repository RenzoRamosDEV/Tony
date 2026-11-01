# Spec Delta

## MODIFIED Requirements

### Requirement: Agents command
`tony agents` SHALL print a table with columns `slot`, `agent`, `role`, `model`, `voice` with one row each for the `front`, `worker` and `guard` agents of `config/tony.yaml` (model shown as its alias) and exit 0; an invalid agent definition SHALL exit non-zero with the validation error on stderr.

#### Scenario: Default agents
- **WHEN** the user runs `tony agents` with the bundled agents
- **THEN** the output has a header and the rows `front jarvis front claude-haiku kokoro/em_alex`, `worker viernes worker claude-sonnet kokoro/ef_dora` and `guard edith guard claude-haiku kokoro/ef_dora,bf_emma` (columns separated by spaces)

#### Scenario: Invalid agent
- **WHEN** `agents/jarvis/agent.md` declares `role: helper`
- **THEN** the command exits non-zero and stderr names the file and the field `role`
