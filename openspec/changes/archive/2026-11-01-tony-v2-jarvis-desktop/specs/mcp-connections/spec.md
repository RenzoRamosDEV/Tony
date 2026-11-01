# Spec Delta

## ADDED Requirements

### Requirement: Masked server stderr log
The standard error of each stdio MCP server SHALL be appended to `logs/mcp/<server>.log` line by line after replacing every secret value known to the task with `***`; non-secret text SHALL be written unchanged. All output written before the server exits SHALL reach the file by the time the task's connections are closed.

#### Scenario: Server echoes a secret on stderr
- **WHEN** `config/.env` defines `GITHUB_TOKEN=s3cr3t`, a stdio server receives it through `env` and writes `auth with s3cr3t` to stderr
- **THEN** `logs/mcp/<server>.log` contains `auth with ***` and not `s3cr3t`

#### Scenario: Ordinary stderr kept
- **WHEN** a stdio server writes `listening on /home/renzo/notas` to stderr and `HOME` comes only from the process environment
- **THEN** the log contains that line unchanged

### Requirement: Server status published
Each connection attempt SHALL publish one `mcp_status` event with the agent name, the server name, `up` and, when down, the masked reason.

#### Scenario: Down server status
- **WHEN** a stdio server's command does not exist
- **THEN** an `mcp_status` event with `up: false` and a reason naming the failure is published, and the other servers' events have `up: true`
