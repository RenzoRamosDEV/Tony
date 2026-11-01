# Spec Delta

## ADDED Requirements

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
