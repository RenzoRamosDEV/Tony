# Spec Delta

## Purpose

Keeps a running Tony session (desktop app or `tony chat`) in step with edits to agents' `tool.json` files and the guard's `policy.yaml`, without restart, while never replacing a valid configuration with a broken one.

## ADDED Requirements

### Requirement: Watched files and hosts
While the desktop app's core or `tony chat` runs, Tony SHALL watch with `watchfiles` every `agents/<agent>/tool/tool.json`, every `agents/<agent>/subagents/<sub>/tool/tool.json` and the guard's `agents/<guard>/policy.yaml`, including files created after start; other files (including `tool.json.lock`) SHALL be ignored. Each changed file SHALL be re-read once per batch of changes, whatever the change kind. `tony run` SHALL NOT watch files.

#### Scenario: Lock file ignored
- **WHEN** `tony mcp add` creates `agents/viernes/tool/tool.json.lock` and replaces `tool.json`
- **THEN** only `agents/viernes/tool/tool.json` is reloaded

#### Scenario: Watching stops with the host
- **WHEN** the desktop core stops
- **THEN** the watcher stops and leaves no running task

### Requirement: Policy applies to the next tool call
A valid change to the guard's `policy.yaml` SHALL become the policy used by the guard for every later verdict, including the next tool call of a task already running, without restart. Limits other than `confirm_timeout_s` SHALL apply from the next task, and `auth` from the next session.

#### Scenario: New deny rule mid-session
- **WHEN** a session is running under the shipped policy and a rule `{match: "filesystem.read_*", verdict: deny, id: "no-read"}` is inserted first in `policy.yaml`
- **THEN** the next `filesystem.read_file` call is denied with rule `no-read`, with no restart

#### Scenario: Policy edited by allow-always
- **WHEN** «Permitir siempre» rewrites `policy.yaml`
- **THEN** the reload is accepted and the next verdict for that tool is `allow` with rule `user-always/<tool id>`

### Requirement: Tool changes apply to the next task or turn
A valid change to a `tool.json` SHALL become that agent's tool declaration for every later task or front-agent turn (servers and natives) without restart; a task or turn already running SHALL keep the servers it started with until it ends.

#### Scenario: Server added with mcp add
- **WHEN** the desktop app is running and `tony mcp add notas <fake server> --agent viernes` is run
- **THEN** the next delegated task offers Viernes the tools `notas.<tool>` and can call them, with no restart and no Python edit

### Requirement: Only changed servers are re-probed
On a valid `tool.json` change Tony SHALL compare the new server entries with the previous valid ones and connect, list and close only the added and changed servers, publishing their `mcp_status` with the agent (or `<agent>/<sub>`) name; each removed server SHALL get an `mcp_status` with `up: false` and reason `removed from tool.json`. Unchanged servers SHALL NOT be started.

#### Scenario: One server changed among two
- **WHEN** Viernes declares servers `a` and `b` and only `b`'s `args` change
- **THEN** only `b` is started (once), an `mcp_status` for `b` is published and none for `a`

#### Scenario: Server removed
- **WHEN** the server `b` is removed from Viernes' `tool.json`
- **THEN** an `mcp_status` with `agent: "viernes"`, `server: "b"`, `up: false` and reason `removed from tool.json` is published and no server is started

### Requirement: Invalid change keeps the previous configuration
A change that leaves a watched file missing, with invalid YAML or JSON, or failing its schema SHALL keep the previous valid configuration in use, publish an `error` event with source `reload` and a message naming the file and the error, and print a warning naming the file and the error on stderr. A later valid change SHALL be applied normally.

#### Scenario: Invalid policy reload
- **WHEN** a valid policy is loaded and `policy.yaml` is saved with invalid YAML
- **THEN** the previous policy keeps applying to the next tool call and an `error` event names `policy.yaml`

#### Scenario: Invalid tool.json reload
- **WHEN** `agents/viernes/tool/tool.json` is saved with `"confirm": []` added
- **THEN** an `error` event names the file and `confirm`, stderr has the warning, and the next task uses Viernes' previous servers

#### Scenario: Recovery after a fix
- **WHEN** after an invalid save `policy.yaml` is saved valid again with a new rule
- **THEN** the new rule applies to the next tool call

### Requirement: Extension without Python edits
Adding an MCP server with `tony mcp add`, a skill as a new folder, and a policy rule by editing `policy.yaml` SHALL each take effect in a running session without editing Python or restarting.

#### Scenario: Three extensions in one session
- **WHEN** in one running session the user adds a fake MCP server with `tony mcp add`, creates a skill folder for Viernes and adds a policy rule allowing the new server's tool
- **THEN** the next delegated task lists the skill in Viernes' prompt, offers the new server's tools, and the new tool's call is audited with the new rule
