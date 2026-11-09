# guard-policy Specification

## Purpose
Defines Edith's permission policy: the guard agent folder, the `policy.yaml` schema, the deterministic model-free algorithm that maps every tool call to `allow`, `confirm` or `deny`, the shipped example policy and its offline evals.

## Requirements

### Requirement: Bundled Edith guard agent
The repository SHALL ship `agents/edith/` with `agent.md` (`role: guard`, `model: claude-haiku`, persona `language: es`, `tone: muy formal, neutral, literal, sin humor`, voice `kokoro/ef_dora,bf_emma`, a system prompt for wording confirmation questions) and `policy.yaml`, and no `tool/` folder.

#### Scenario: Bundled Edith validates
- **WHEN** `agents/edith/` is loaded with the default configuration
- **THEN** loading succeeds with role `guard`, model alias `claude-haiku`, voice `kokoro/ef_dora,bf_emma` and no tools

#### Scenario: Bundled policy validates
- **WHEN** `agents/edith/policy.yaml` is loaded
- **THEN** loading succeeds and its `default` is not `allow`

### Requirement: Policy file location
The policy SHALL be read from `agents/<guard>/policy.yaml`, where `<guard>` is the `guard` agent folder from `config/tony.yaml`. A missing file, invalid YAML or a schema violation MUST fail before any tool call with an error naming the file and, when applicable, the dotted field.

#### Scenario: Missing policy
- **WHEN** `agents/edith/policy.yaml` does not exist
- **THEN** the run fails before the worker starts with an error naming `agents/edith/policy.yaml`

#### Scenario: Invalid verdict
- **WHEN** the second rule declares `verdict: maybe`
- **THEN** loading fails with an error naming the file and the field `rules.1.verdict`

### Requirement: Policy schema
`policy.yaml` SHALL contain `default` (`allow|confirm|deny`), `rules` (ordered list, default empty), `limits` and `auth`. Unknown keys MUST be rejected at any level. `limits` defaults: `tool_timeout_s` 20, `task_timeout_s` 300, `confirm_timeout_s` 60, `max_denied_retries` 3, `token_alert` 50000, `max_steps_per_agent` 30. `auth` defaults: `pin_required` true, `lock_after_min` 30.

#### Scenario: Limits default
- **WHEN** a policy declares only `default: confirm`
- **THEN** it loads with empty `rules`, every `limits` value at its default and `auth` at its defaults

#### Scenario: Unknown key rejected
- **WHEN** `limits` contains `max_cost: 3`
- **THEN** loading fails with an error naming the file and the field `limits.max_cost`

#### Scenario: Default required
- **WHEN** the policy omits `default`
- **THEN** loading fails with an error naming the file and the field `default`

### Requirement: Rule schema
A rule SHALL have `match` (one pattern string or a non-empty list of them), `verdict` (`allow|confirm|deny`), optional `id` and optional `when` with any of `path_outside` (list of directories), `args_regex` (a valid Python regex) and `numeric_above` (`{arg, value}` with a numeric `value`). Without `id`, the id SHALL be `<first pattern>/<verdict>`.

#### Scenario: Derived rule id
- **WHEN** a rule declares `match: ["filesystem.delete*", "filesystem.move_file"]` and `verdict: confirm` without `id`
- **THEN** its id is `filesystem.delete*/confirm`

#### Scenario: Explicit rule id
- **WHEN** a rule declares `id: no-shell`
- **THEN** its id is `no-shell`

#### Scenario: Invalid regex rejected
- **WHEN** a rule declares `when: {args_regex: "(unclosed"}`
- **THEN** loading fails with an error naming the file and the field `rules.<n>.when.args_regex`

#### Scenario: Empty match list rejected
- **WHEN** a rule declares `match: []`
- **THEN** loading fails with an error naming the file and the field `rules.<n>.match`

### Requirement: First-match evaluation
For a tool id and its args, the verdict SHALL be the first rule, in file order, having a pattern that matches the tool id with case-sensitive `fnmatch` AND whose every `when` condition holds; if no rule wins, `default` applies with rule id `default`. Evaluation MUST NOT call any model.

#### Scenario: First matching rule wins
- **WHEN** `shell.run` is called with `command="ls"` under the shipped policy
- **THEN** the `shell.run/deny` rule does not hold, the next rule wins and the verdict is `confirm` with rule `shell.run/confirm`

#### Scenario: List pattern matches second item
- **WHEN** `filesystem.move_file` is called under the shipped policy
- **THEN** the verdict is `confirm` with rule `filesystem.delete*/confirm`

#### Scenario: Case-sensitive match
- **WHEN** `Filesystem.read_file` is called under the shipped policy
- **THEN** no rule matches and the verdict is the default `confirm` with rule `default`

#### Scenario: Default deny
- **WHEN** a policy has `default: deny`, no rule matches `foo.bar` and `foo.bar` is called
- **THEN** the verdict is `deny` with rule `default`

### Requirement: path_outside condition
`path_outside` SHALL hold when any string value under the top-level arg keys `path`, `source`, `destination`, or any string item of `paths`, after `~` expansion and absolute normalisation, is not equal to or inside any listed directory (also `~`-expanded and normalised). It SHALL NOT hold when no such value exists.

#### Scenario: Write inside an allowed folder
- **WHEN** `filesystem.write_file` is called with `path="~/notas/a.md"` under the shipped policy
- **THEN** the verdict is `allow` with rule `filesystem.write_file/allow`

#### Scenario: Write outside the allowed folders
- **WHEN** `filesystem.write_file` is called with `path="/tmp/a.md"` under the shipped policy
- **THEN** the verdict is `confirm` with rule `filesystem.write_file/confirm`

#### Scenario: Dot-dot escape
- **WHEN** `filesystem.write_file` is called with `path="~/notas/../secretos/x.md"` and `content="hola"`
- **THEN** the verdict is `confirm`

#### Scenario: Sibling prefix is outside
- **WHEN** `filesystem.write_file` is called with `path="~/notasx/a.md"`
- **THEN** the verdict is `confirm`

#### Scenario: One of several paths outside
- **WHEN** a rule with `path_outside: ["~/notas"]` is evaluated for args `{"paths": ["~/notas/a.md", "/etc/passwd"]}`
- **THEN** the condition holds

### Requirement: args_regex condition
`args_regex` SHALL hold when `re.search` with the rule's pattern matches any string value found recursively in the args (nested objects and lists; keys excluded).

#### Scenario: Dangerous shell command
- **WHEN** `shell.run` is called with `command="sudo dnf update"` under the shipped policy
- **THEN** the verdict is `deny` with rule `shell.run/deny`

#### Scenario: Nested value matches
- **WHEN** a rule has `args_regex: "secreto"` and the args are `{"opts": {"tags": ["a", "secreto"]}}`
- **THEN** the condition holds

### Requirement: numeric_above condition
`numeric_above` SHALL hold when `args[arg]` is a number (booleans excluded) strictly greater than `value`; a missing or non-numeric arg makes it not hold.

#### Scenario: Equal value does not hold
- **WHEN** a rule has `numeric_above: {arg: amount, value: 100}` and `amount` is `100`
- **THEN** the condition does not hold

#### Scenario: Greater value holds
- **WHEN** the same rule is evaluated with `amount` equal to `100.5`
- **THEN** the condition holds

#### Scenario: Non-numeric arg
- **WHEN** the same rule is evaluated with `amount` equal to `"500"` or `true`
- **THEN** the condition does not hold

### Requirement: Decision latency
Evaluating one call against the shipped policy SHALL take less than 5 ms on average.

#### Scenario: Thousand evaluations
- **WHEN** 1000 calls are evaluated against the shipped policy
- **THEN** the mean evaluation time is below 5 ms

### Requirement: Shipped example policy
The bundled `agents/edith/policy.yaml` SHALL be exactly the following policy (comments allowed), including allow rules for the native tools `tony.read_skill` and `tony.run_subagent`:

#### Scenario: Shipped policy content
- **WHEN** the bundled policy is loaded
- **THEN** it is equivalent to:
```yaml
default: confirm
rules:
  - match: "filesystem.read_*"
    verdict: allow
  - match: "filesystem.list_*"
    verdict: allow
  - match: "filesystem.write_file"
    verdict: confirm
    when:
      path_outside: ["~/notas", "~/proyectos"]
  - match: "filesystem.write_file"
    verdict: allow
  - match: ["filesystem.delete*", "filesystem.move_file"]
    verdict: confirm
  - match: "shell.run"
    verdict: deny
    when:
      args_regex: "(rm -rf|sudo|mkfs|curl .*\\| *sh)"
  - match: "shell.run"
    verdict: confirm
  - match: "github.search_*"
    verdict: allow
  - match: "github.*"
    verdict: confirm
  - match: ["google-calendar.list-*", "google-calendar.search-events", "google-calendar.get-event", "google-calendar.free-busy"]
    verdict: allow
  - match: ["google-calendar.create-event", "google-calendar.update-event", "google-calendar.delete-event"]
    verdict: confirm
  - match: "google-calendar.*"
    verdict: confirm
  - match: ["gmail.read_email", "gmail.search_emails", "gmail.list_email_labels", "gmail.download_attachment", "gmail.list_filters", "gmail.get_filter"]
    verdict: allow
  - match: ["gmail.send_email", "gmail.draft_email", "gmail.delete_email", "gmail.delete_label", "gmail.batch_delete_emails", "gmail.delete_filter"]
    verdict: confirm
  - match: "gmail.*"
    verdict: confirm
  - match: ["gdrive.gdrive_search", "gdrive.gdrive_read_file", "gdrive.gsheets_read"]
    verdict: allow
  - match: "gdrive.gsheets_update_cell"
    verdict: confirm
  - match: "gdrive.*"
    verdict: confirm
  - match: ["obsidian.obsidian_list_vaults", "obsidian.obsidian_read_note", "obsidian.obsidian_search_vault"]
    verdict: allow
  - match: ["obsidian.obsidian_create_note", "obsidian.obsidian_edit_note", "obsidian.obsidian_delete_note", "obsidian.obsidian_move_note"]
    verdict: confirm
  - match: "obsidian.*"
    verdict: confirm
  - match: ["music.music_play", "music.music_queue"]
    verdict: confirm
  - match: "music.*"
    verdict: allow
  - match: ["tony.read_skill", "tony.run_subagent"]
    verdict: allow
limits: {tool_timeout_s: 20, task_timeout_s: 300, confirm_timeout_s: 60, max_denied_retries: 3, token_alert: 50000, max_steps_per_agent: 30}
auth: {pin_required: true, lock_after_min: 30}
```

### Requirement: Offline policy evals
`evals/politica.yaml` SHALL hold at least 20 cases `{tool, args, expected}` evaluated against the shipped policy by a default offline test; all MUST pass. A case MAY add `extra_rules` (rule list evaluated before the shipped rules) only to exercise a condition the shipped policy lacks. Cases SHALL cover every verdict, every `when` condition (boundary paths, `~`, regex hit/miss, numeric equal/above), list patterns, ordering and the default.

#### Scenario: Eval case passes
- **WHEN** the eval file contains
```yaml
- tool: filesystem.write_file
  args: {path: "~/notas/../secretos/x.md", content: "hola"}
  expected: confirm
```
- **THEN** the default test suite evaluates it against the shipped policy and it passes

#### Scenario: Numeric case with extra rules
- **WHEN** a case declares `extra_rules: [{match: "pagos.transferir", verdict: deny, when: {numeric_above: {arg: importe, value: 100}}}]` and `tool: pagos.transferir`
- **THEN** `args: {importe: 100}` expects the default `confirm` and `args: {importe: 150}` expects `deny`

#### Scenario: Coverage of the eval file
- **WHEN** the default test suite loads `evals/politica.yaml`
- **THEN** it has at least 20 cases and the set of `expected` verdicts is `{allow, confirm, deny}`

### Requirement: Allow-always rule insertion
Answering «Permitir siempre» SHALL insert `{match: "<exact tool id>", verdict: allow, id: "user-always/<tool id>"}` as the first rule of the guard's `policy.yaml`, keep the other keys and the remaining rules in their order, allow the pending call and audit it with `user_decision: "allow"`. If a rule with that id exists, the file SHALL be left unchanged.

#### Scenario: Rule inserted at the top
- **WHEN** the user answers «Permitir siempre» to `filesystem.write_file` under the shipped policy
- **THEN** the first rule of `agents/edith/policy.yaml` is `{match: "filesystem.write_file", verdict: allow, id: "user-always/filesystem.write_file"}`, the next rules are the shipped rules in their original order, the call runs and the audit line has `verdict: "confirm"` and `user_decision: "allow"`

#### Scenario: Not duplicated
- **WHEN** the policy already has a rule with id `user-always/filesystem.write_file` and the user answers «Permitir siempre» again
- **THEN** the policy file content is unchanged

### Requirement: Allow-always offered only for tools without deny rules
«Permitir siempre» SHALL be offered for a pending confirmation only when no rule of the current policy with `verdict: deny` has a pattern that matches the pending tool id (case-sensitive `fnmatch`), regardless of that rule's `when` conditions. The confirmation request SHALL carry this as `allow_always` (`true` when offered). An `always` answer to a request with `allow_always: false` SHALL allow the pending call once and MUST NOT modify `policy.yaml`.

#### Scenario: Tool with a deny rule
- **WHEN** under the shipped policy a confirmation for `shell.run` is pending
- **THEN** the request has `allow_always: false` and «Permitir siempre» is not offered

#### Scenario: Tool without a deny rule
- **WHEN** under the shipped policy a confirmation for `filesystem.delete_file` is pending
- **THEN** the request has `allow_always: true` and «Permitir siempre» is offered

#### Scenario: Always answer for an ineligible tool
- **WHEN** a confirmation for `shell.run` with `allow_always: false` is answered with decision `always`
- **THEN** the call runs once, `policy.yaml` is unchanged and the next `shell.run` call asks again

### Requirement: Allow-always takes effect
After an allow-always answer, later calls to the same tool id SHALL be allowed without asking: in the running task immediately, and in later tasks through the rewritten policy (verdict `allow`, rule `user-always/<tool id>`).

#### Scenario: Next task
- **WHEN** after «Permitir siempre» for `filesystem.write_file` a new task calls `filesystem.write_file` with `path="/tmp/a.md"`
- **THEN** the verdict is `allow` with rule `user-always/filesystem.write_file` and no question is asked

#### Scenario: Same task
- **WHEN** the same task calls `filesystem.write_file` again after the allow-always answer
- **THEN** no new `needs_confirmation` event is published and the call runs

### Requirement: Safe policy rewrite
The rewritten policy SHALL be validated against the policy schema before replacing the file, and the file SHALL be replaced atomically. If validation or writing fails, the file SHALL be left unchanged, an `error` event published, and the pending call still allowed once.

#### Scenario: Unwritable policy
- **WHEN** the folder `agents/edith/` is not writable and the user answers «Permitir siempre»
- **THEN** the call runs, an `error` event naming the policy file is published and the file is unchanged
