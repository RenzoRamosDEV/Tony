# guard-audit Specification

## Purpose
Defines the append-only audit trail of every Edith verdict in `logs/audit.jsonl`, how arguments are hashed and previewed without leaking secrets, and the `tony audit` command that lists it.

## Requirements

### Requirement: One audit line per verdict
Every verdict SHALL append exactly one JSON line to `logs/audit.jsonl` (folder created when missing) with `ts` (UTC ISO 8601), `task_id`, `agent`, `tool`, `args_hash`, `args_preview`, `verdict`, `rule`, `user_decision` and `duration_ms` (integer, from the start of judging to the final decision, confirmation wait included).

#### Scenario: Audit line for a confirmed delete
- **WHEN** Viernes calls `filesystem.delete_file` with `{"path": "/home/renzo/notas/viejo.md"}` and the user confirms after about 8 s
- **THEN** one line like the following is appended:
```json
{"ts": "2026-11-01T10:15:02Z", "task_id": "3f2a9c1e0b7d4e8f9a6b5c4d3e2f1a0b", "agent": "viernes", "tool": "filesystem.delete_file", "args_hash": "9b1c…", "args_preview": "{\"path\": \"/home/renzo/notas/viejo.md\"}", "verdict": "confirm", "rule": "filesystem.delete*/confirm", "user_decision": "allow", "duration_ms": 8423}
```

#### Scenario: Allowed write audited
- **WHEN** Viernes calls `filesystem.write_file` with `path="~/notas/a.md"` under the shipped policy
- **THEN** exactly one audit line is written with `verdict: "allow"`, `rule: "filesystem.write_file/allow"` and `user_decision: null`

#### Scenario: Default deny audited
- **WHEN** a policy has `default: deny` and Viernes calls `foo.bar`
- **THEN** the audit line has `verdict: "deny"`, `rule: "default"` and `user_decision: null`

### Requirement: User decision field
`user_decision` SHALL be `null` for `allow` and `deny` verdicts and one of `allow`, `deny` or `timeout` for `confirm` verdicts. Any answer other than yes, and a missing channel, SHALL be recorded as `deny`.

#### Scenario: Timed-out confirmation
- **WHEN** a confirmation for `filesystem.delete_file` times out
- **THEN** the audit line has `verdict: "confirm"` and `user_decision: "timeout"`

#### Scenario: Rejected confirmation
- **WHEN** the user answers `no`
- **THEN** the audit line has `user_decision: "deny"`

### Requirement: Agent field
`agent` SHALL be the calling agent's name, or `<agent>/<subagent>` when the call comes from a subagent.

#### Scenario: Worker call
- **WHEN** Viernes makes a call
- **THEN** `agent` is `viernes`

### Requirement: Argument hash
`args_hash` SHALL be the lowercase SHA-256 hex digest of the canonical JSON of the args (sorted keys, separators `, ` and `: `, non-ASCII kept), so equal args always produce equal hashes regardless of key order.

#### Scenario: Key order irrelevant
- **WHEN** two calls have args `{"b": 1, "a": 2}` and `{"a": 2, "b": 1}`
- **THEN** both audit lines have the same `args_hash`, equal to the SHA-256 of `{"a": 2, "b": 1}`

### Requirement: Masked argument preview
`args_preview` SHALL be the canonical JSON of the args with masked secrets, truncated to 200 characters with suffix `…` when longer. Masking SHALL replace with `***` the value of any key matching `(?i)(token|key|secret|password|passwd|authorization|pin)` and any string containing a value defined in `config/.env`.

#### Scenario: Secret-looking key masked
- **WHEN** the args are `{"path": "a.md", "api_key": "abc123"}`
- **THEN** `args_preview` is `{"api_key": "***", "path": "a.md"}`

#### Scenario: Env value masked
- **WHEN** `config/.env` defines `GITHUB_TOKEN=s3cr3t` and the args are `{"q": "token s3cr3t"}`
- **THEN** `args_preview` contains `***` and not `s3cr3t`

#### Scenario: Process variable not masked
- **WHEN** `HOME=/home/renzo` comes only from the process environment and the args are `{"path": "/home/renzo/notas/a.md"}`
- **THEN** `args_preview` is `{"path": "/home/renzo/notas/a.md"}`

#### Scenario: Truncation boundary
- **WHEN** the canonical JSON is exactly 200 characters, or 201 characters
- **THEN** the preview is unchanged in the first case and is the first 200 characters followed by `…` in the second

### Requirement: Audit command
`tony audit [--today] [--verdict allow|confirm|deny]` SHALL print the matching audit lines, oldest first, as a table with columns `ts`, `agent`, `tool`, `verdict`, `rule`, `user_decision`, and exit 0, also when nothing matches or the file does not exist. `--today` SHALL keep lines whose `ts` falls on the current local date.

#### Scenario: Filter by verdict
- **WHEN** the audit log has one `allow` and one `deny` line and the user runs `tony audit --verdict deny`
- **THEN** only the `deny` line is printed under the header and the exit code is 0

#### Scenario: Today filter uses local date
- **WHEN** the local timezone is UTC+1, it is 2026-11-01 locally, and lines have `ts` `2026-10-31T23:30:00Z` and `2026-10-31T22:30:00Z`
- **THEN** `tony audit --today` prints only the first line

#### Scenario: Empty log
- **WHEN** `logs/audit.jsonl` does not exist
- **THEN** `tony audit` prints only the header and exits 0

#### Scenario: Invalid verdict option
- **WHEN** the user runs `tony audit --verdict maybe`
- **THEN** the command exits non-zero with a usage error
