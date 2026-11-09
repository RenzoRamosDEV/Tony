## ADDED Requirements

### Requirement: Typed action preview
A confirmation request SHALL carry a `preview` mapping of masked, authoritative fields, each capped at 2000 characters with a trailing `…` when cut. Fields are: `to`, `cc`, `subject`, `body` for `gmail.send_email` and `gmail.draft_email`; `path`, `bytes` (UTF-8 size of the content) and `content` for `filesystem.write_file`; `summary`, `start`, `end`, `attendees` for `google-calendar.create-event` and `update-event`; otherwise `args` as JSON.

#### Scenario: Email preview
- **WHEN** `gmail.send_email` needs confirmation with a 5000-character body
- **THEN** `preview.body` has 2000 characters followed by `…` and `to`, `cc`, `subject` are present when given

#### Scenario: Unknown tool
- **WHEN** a tool without a typed preview needs confirmation
- **THEN** `preview` is `{"args": "<args JSON>"}` capped at 2000 characters

### Requirement: Preview masking
Preview fields SHALL be masked with the same secret masking as the audit preview, including values under secret-named keys, before capping.

#### Scenario: Secret in file content
- **WHEN** `filesystem.write_file` content contains a known secret value
- **THEN** `preview.content` shows the mask instead of the value

### Requirement: Approval identity and binding
Each confirmation request SHALL create an approval with a fresh `approval_id` (uuid4), the `args_digest` (sha256 of the canonical JSON of the unmasked args), the `policy_version` (sha256 of the guard's `policy.yaml` content) and `expires_at` (now plus `confirm_timeout_s`).

#### Scenario: Fields present
- **WHEN** a call needs confirmation
- **THEN** the request carries all four values, and `expires_at` is `confirm_timeout_s` seconds after the request time

### Requirement: Answer acceptance
The broker SHALL accept an answer only when its task matches the pending approval, the approval has not expired and an `approval_id`, when given, equals the pending one. A mismatched or expired answer SHALL be ignored and the approval stays pending until it times out. An answer without `approval_id` SHALL still be accepted while one approval is pending.

#### Scenario: Wrong approval id
- **WHEN** an answer carries an `approval_id` different from the pending one
- **THEN** it is ignored and the call is not approved

#### Scenario: Late answer
- **WHEN** an answer arrives after `expires_at`
- **THEN** it is ignored and the ruling is `timeout`

#### Scenario: Legacy answer
- **WHEN** an answer has no `approval_id` and one approval is pending for the task
- **THEN** it is accepted as before

### Requirement: Policy change re-evaluates
When the policy version after an affirmative answer differs from the approval's, the guard SHALL discard the answer and evaluate and judge the call again from scratch under the current policy, at most twice; if it still changes, the call SHALL be denied.

#### Scenario: Policy edited while waiting
- **WHEN** `policy.yaml` is replaced by a policy denying the tool while the user is answering yes
- **THEN** the ruling is `deny` with the new rule and the tool does not run

#### Scenario: Policy edited to still require confirmation
- **WHEN** the policy changes but the tool still needs confirmation
- **THEN** a new approval with a new `approval_id` is requested

### Requirement: Approval never widens permissions
An approval SHALL apply to exactly one call. It MUST NOT grant any permission beyond that call, bypass the PIN or confirmation requirements, or be created from model-written text.

#### Scenario: One call only
- **WHEN** the user approves a call and the agent repeats the same call
- **THEN** the repeated call is judged and confirmed again (unless an existing always-allow rule applies)
