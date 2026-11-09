## ADDED Requirements

### Requirement: Needs-confirmation approval fields
The `needs_confirmation` event SHALL carry the optional fields `approval_id`, `args_digest`, `policy_version`, `expires_at` (ISO timestamp) and `preview` (field mapping), in addition to its existing fields, which MUST NOT change.

#### Scenario: Event shape
- **WHEN** a confirmation is requested
- **THEN** the event has `approval_id`, `args_digest`, `policy_version`, `expires_at` and `preview` plus `task_id`, `tool`, `args_preview`, `question` and `allow_always`

#### Scenario: Old consumer
- **WHEN** a consumer ignores the new fields
- **THEN** it still handles the event as before

### Requirement: Confirm command approval id
The `confirm` command SHALL accept an optional `approval_id`. Without it, behavior is unchanged; with it, the broker's answer-acceptance rules apply.

#### Scenario: Id supplied
- **WHEN** `confirm` is sent with `task_id`, `decision` and the pending `approval_id`
- **THEN** the pending approval is answered

#### Scenario: Unknown field still rejected
- **WHEN** `confirm` is sent with an unrelated extra field
- **THEN** parsing fails naming the field
