# Spec Delta

## MODIFIED Requirements

### Requirement: Secrets source
Placeholder variables SHALL be read from `config/.env` and the process environment, the process environment taking precedence. A secret SHALL be any non-empty value defined in `config/.env`, plus the value of any placeholder variable whose name matches `(?i)(token|key|secret|password|passwd|authorization|pin)`. Other process variables (e.g. `HOME`) MUST NOT be treated as secrets. `config/.env` MUST NOT be required to exist for offline runs.

#### Scenario: Missing env file
- **WHEN** `config/.env` does not exist and no placeholder needs a missing variable
- **THEN** configuration loads without error

#### Scenario: Env file values are secrets
- **WHEN** `config/.env` defines `GITHUB_TOKEN=s3cr3t` and `NOTAS_DIR=/srv/notas`
- **THEN** both `s3cr3t` and `/srv/notas` are secrets

#### Scenario: Secret-looking process variable
- **WHEN** `API_KEY=k3y` comes only from the process environment and a server uses `${API_KEY}`
- **THEN** `k3y` is a secret

#### Scenario: Ordinary process variable
- **WHEN** `HOME=/home/renzo` comes only from the process environment and a server uses `${HOME}`
- **THEN** `/home/renzo` is not a secret

### Requirement: Secrets never leak
No agent prompt, tool result returned to an agent, task log line, audit line or CLI output SHALL contain a secret value; every occurrence of a secret MUST be replaced by `***` before it leaves the core. Values that are not secrets SHALL be left unchanged.

#### Scenario: Tool echoes a secret
- **WHEN** a tool result contains the value `s3cr3t` of `GITHUB_TOKEN` defined in `config/.env`
- **THEN** the result passed to the agent and the `tool_result` log event contain `***` instead of `s3cr3t`

#### Scenario: Home path resolved but not masked
- **WHEN** `tool.json` declares `"args": ["${HOME}/notas"]`, `HOME=/home/renzo` comes only from the process environment, and a tool result contains `/home/renzo/notas/a.md`
- **THEN** the server receives the argument `/home/renzo/notas`, and the result passed to the agent and the `tool_result` log event contain `/home/renzo/notas/a.md` unmasked

#### Scenario: Env value masked even when unused
- **WHEN** `config/.env` defines `GITHUB_TOKEN=s3cr3t`, no server uses `${GITHUB_TOKEN}`, and a tool result contains `s3cr3t`
- **THEN** the result passed to the agent contains `***` instead of `s3cr3t`
