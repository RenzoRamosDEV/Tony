## ADDED Requirements

### Requirement: Policy explain
`tony policy explain TOOL [--args JSON]` SHALL evaluate the tool with the guard's current policy using the real `evaluate` and print the verdict, the rule id and the 1-based position of the matching rule (`default` when no rule matches). Invalid `--args` JSON, or JSON that is not an object, SHALL exit 2 with a `tony:` message. It MUST NOT modify any file.

#### Scenario: Rule match
- **WHEN** the shipped policy is used and `tony policy explain shell.run` is run
- **THEN** stdout shows the verdict and rule id from `evaluate` and the 1-based index of that rule

#### Scenario: Default
- **WHEN** no rule matches
- **THEN** stdout shows the policy default verdict, rule `default` and no position

#### Scenario: Bad args
- **WHEN** `--args '[1]'` is given
- **THEN** the exit code is 2

### Requirement: Policy grants listing
`tony policy grants` SHALL list the rules whose id starts with `user-always/`, one line per rule with its tool id, in policy order; with none it SHALL print a message saying there are no grants.

#### Scenario: Two grants
- **WHEN** the policy has `user-always/a.x` and `user-always/b.y`
- **THEN** both tool ids are listed

#### Scenario: None
- **WHEN** the policy has no such rule
- **THEN** a no-grants message is printed and the exit code is 0

### Requirement: Policy revoke
`tony policy revoke TOOL` SHALL remove the rule with id `user-always/TOOL` from the guard's `policy.yaml`, keeping every other rule, key and the rule order. The rewritten policy SHALL be validated before an atomic replacement, using the same mechanism as allow-always insertion. If no such grant exists it SHALL print a message, exit 1 and leave the file untouched; on write failure the file stays unchanged.

#### Scenario: Revoke existing grant
- **WHEN** the policy has rules `[user-always/fs.write, shell.deny, default-rules...]` and the user revokes `fs.write`
- **THEN** the remaining rules and keys are identical and in the same order

#### Scenario: Unknown grant
- **WHEN** the user revokes a tool without a grant
- **THEN** the exit code is 1 and the file bytes are unchanged

#### Scenario: Only grants are removable
- **WHEN** a shipped rule has id `shell.run/deny` and the user runs `revoke shell.run`
- **THEN** the exit code is 1 and the file is unchanged

### Requirement: Policy simulate
`tony policy simulate FILE` SHALL read a JSON list of `{tool, args, expect}`, evaluate each case with the real `evaluate`, print pass or fail per case (with the actual verdict on failure) and exit 1 if any case fails. A malformed file or case SHALL exit 2 with a `tony:` message naming the case index.

#### Scenario: All pass
- **WHEN** every case's `expect` equals the evaluated verdict
- **THEN** every line says pass and the exit code is 0

#### Scenario: One fails
- **WHEN** one case expects `allow` but the policy yields `confirm`
- **THEN** that line says fail with `confirm` and the exit code is 1

#### Scenario: Malformed case
- **WHEN** case 2 lacks `tool`
- **THEN** the exit code is 2 and the message names case 2

### Requirement: Policy commands do not weaken the guard
`tony policy` commands MUST NOT be exposed as model tools or core commands, MUST NOT add allow rules, and MUST NOT alter `evaluate` or first-match semantics. The shipped `agents/edith/policy.yaml` SHALL remain unchanged by this capability.

#### Scenario: No tool exposure
- **WHEN** the native tool registry and core command union are inspected
- **THEN** neither contains a policy explain, revoke or simulate entry
