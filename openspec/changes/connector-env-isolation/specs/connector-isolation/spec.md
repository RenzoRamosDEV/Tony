## Purpose
Defines the opt-in environment isolation of stdio connectors and the doctor warning for allowlisted variables missing from the host.

## ADDED Requirements

### Requirement: Isolation is opt-in and non-escalating
Connector environment isolation SHALL apply only to stdio servers that declare `isolation`. It MUST NOT grant any permission, bypass any confirmation or PIN, or change policy; every tool call of an isolated server continues through the guard.

#### Scenario: Guard still applies
- **WHEN** an isolated server's tool requires confirmation by policy
- **THEN** the confirmation is still requested before the call

#### Scenario: Out of scope behaviors
- **WHEN** a server declares `isolation`
- **THEN** only its environment variables are restricted, with no filesystem, network or operating-system sandboxing

### Requirement: Doctor warns on unset allowlisted variables
`tony doctor` SHALL report, for each stdio server whose `env_allow` names a variable not set in the host environment, a row with status `warn` naming the server and the missing variables. A server whose allowlisted variables are all set, or that has no `env_allow` entries, SHALL produce no warning row. The check MUST NOT start the server.

#### Scenario: Missing variable
- **WHEN** a server declares `env_allow` equal to `["GITHUB_TOKEN"]` and the host does not define it
- **THEN** the doctor shows a `warn` row for that server naming `GITHUB_TOKEN`

#### Scenario: All variables present
- **WHEN** every `env_allow` variable is set in the host
- **THEN** the doctor shows no isolation warning for that server

#### Scenario: Warning does not fail the doctor
- **WHEN** the only non-ok row is an isolation `warn`
- **THEN** the doctor exit status is the same as for any other `warn`

#### Scenario: Several missing variables
- **WHEN** two allowlisted variables are missing
- **THEN** a single `warn` row for the server names both, in sorted order
