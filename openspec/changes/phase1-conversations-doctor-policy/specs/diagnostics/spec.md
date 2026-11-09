## ADDED Requirements

### Requirement: Doctor command output
`tony doctor` SHALL run the installation checks and print a table `check | status | hint` with one row per check, where status is `ok`, `warn` or `fail` and hint is a single line. It SHALL exit 1 if any check is `fail`, otherwise 0.

#### Scenario: Healthy installation
- **WHEN** every check passes
- **THEN** all rows have status `ok` and the exit code is 0

#### Scenario: Failure
- **WHEN** at least one check is `fail`
- **THEN** the exit code is 1 and its hint says what to fix

#### Scenario: Warnings only
- **WHEN** only `warn` rows exist
- **THEN** the exit code is 0

### Requirement: Doctor checks are local and non-executing
Doctor checks MUST NOT start an MCP server, run a tool, execute a declared command, import optional heavy modules or open a network connection. They SHALL only read files, inspect PATH, the environment and importable-module metadata.

#### Scenario: No side effects
- **WHEN** the doctor runs with fakes for PATH lookup and module discovery
- **THEN** no subprocess is spawned and no socket is opened

### Requirement: Definition files check
The doctor SHALL check that `tony.yaml` and, for every agent folder, `agent.md`, `tool.json` and `policy.yaml` where present, load with the existing loaders without `DefinitionError`. A failure SHALL be `fail` with the error's file and message as the hint; one broken file MUST NOT stop the other checks.

#### Scenario: Broken tool.json
- **WHEN** `agents/viernes/tool/tool.json` is invalid JSON
- **THEN** its row is `fail` naming that file and the remaining checks still run

#### Scenario: Valid definitions
- **WHEN** all files load
- **THEN** the definitions rows are `ok`

### Requirement: MCP server declaration check
For each declared stdio server the doctor SHALL check that its command is found on PATH, treating a bare `python` or `python3` as found (resolved as the existing stdio command rule does); a missing command is `fail`. For each HTTP server it SHALL check that the URL scheme is `http` or `https`; otherwise `fail`.

#### Scenario: Missing command
- **WHEN** a stdio server declares `npx` and `npx` is not on PATH
- **THEN** its row is `fail` with a hint to install it

#### Scenario: Bare python
- **WHEN** a stdio server declares `python`
- **THEN** its row is `ok` regardless of PATH

#### Scenario: Bad URL scheme
- **WHEN** an HTTP server declares `ftp://host/mcp`
- **THEN** its row is `fail`

### Requirement: Placeholder resolution check
The doctor SHALL check that every `${NAME}` placeholder used in a server's command, args, env, url or headers resolves to a variable defined in the environment or `config/.env`. An undefined variable is `fail`. Output MUST contain placeholder names only and never variable values.

#### Scenario: Undefined variable
- **WHEN** a server uses `${GMAIL_TOKEN}` and it is not defined
- **THEN** its row is `fail` and the hint names `GMAIL_TOKEN`

#### Scenario: Values never printed
- **WHEN** `${API_KEY}` is defined as `s3cret`
- **THEN** the full output does not contain `s3cret`

### Requirement: Optional dependency checks
The doctor SHALL report the optional voice modules (the names the voice engine loader requires) as `warn` when not importable, with the install hint. When a server named `music` is declared, it SHALL check that `yt-dlp` and `mpv` are found, `warn` when missing, and SHALL skip those checks otherwise.

#### Scenario: Voice extra missing
- **WHEN** a required voice module cannot be found
- **THEN** the voice row is `warn`, not `fail`

#### Scenario: Music not declared
- **WHEN** no `music` server is declared
- **THEN** no `yt-dlp` or `mpv` row is printed
