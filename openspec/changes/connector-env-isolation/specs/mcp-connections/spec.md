## ADDED Requirements

### Requirement: Isolated stdio environment
When a stdio server declares `isolation`, Tony SHALL start its process with an environment containing exactly: each `env_allow` variable that is set in the host environment (with its host value), the server's declared `env` (after placeholder resolution), and the host values of `PATH`, `HOME`, `LANG` and `LC_ALL` when set. No other variable MUST be present, including those the MCP SDK would add by default.

#### Scenario: Non-allowed host variable absent
- **WHEN** the host has `SECRET_X=1`, `GITHUB_TOKEN=t` and `USER=u`, and a stdio server declares `isolation` with `env_allow` equal to `["GITHUB_TOKEN"]`
- **THEN** the process sees `GITHUB_TOKEN=t` and `PATH`, and does not see `SECRET_X`, `USER`, `SHELL`, `TERM` or `LOGNAME`

#### Scenario: Declared env is delivered
- **WHEN** an isolated server also declares `env` with `API_KEY` set to `k`
- **THEN** the process sees `API_KEY=k`

#### Scenario: Declared env wins over host value
- **WHEN** `env_allow` names `TOKEN`, the host has `TOKEN=host` and the declared `env` sets `TOKEN` to `declared`
- **THEN** the process sees `TOKEN=declared`

#### Scenario: Allowed variable unset in host
- **WHEN** `env_allow` names a variable the host does not define
- **THEN** the variable is absent from the process and the server still connects

### Requirement: Isolation launch is transparent
An isolated server SHALL behave as a normal stdio server for connection, tools, timeouts, reconnect, stderr logging and masking. Values of the isolated environment MUST NOT appear in the process arguments, and a command that cannot be launched SHALL mark the server down with a reason like any failed connection.

#### Scenario: Tools listed under isolation
- **WHEN** an isolated stdio server connects
- **THEN** its tools are cataloged as `<server>.<tool>` and are callable

#### Scenario: Launch failure
- **WHEN** an isolated server's command does not exist
- **THEN** that server is marked down with a reason and the other servers are unaffected

### Requirement: Servers without isolation are unchanged
A stdio server that does not declare `isolation` SHALL keep receiving the SDK default inherited variables merged with its declared `env`, exactly as before this capability.

#### Scenario: No isolation declared
- **WHEN** a stdio server declares only `command` and `env`
- **THEN** its environment is the same as before the isolation option existed
