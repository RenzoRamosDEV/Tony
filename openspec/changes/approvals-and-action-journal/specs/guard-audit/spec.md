## ADDED Requirements

### Requirement: Approval id in audit line
An audit line for a `confirm` verdict SHALL include the `approval_id` of the approval that was asked. Lines for `allow` and `deny` verdicts SHALL NOT include the field. Existing fields are unchanged.

#### Scenario: Confirmed call
- **WHEN** a confirmation is asked with approval id `A1` and the user answers yes
- **THEN** the audit line has `verdict: "confirm"`, `user_decision: "allow"` and `approval_id: "A1"`

#### Scenario: Allowed call
- **WHEN** a call is allowed by policy
- **THEN** its audit line has no `approval_id`

### Requirement: Re-evaluated approvals audited once
When a policy change forces re-evaluation, only the final ruling SHALL be appended to the audit trail.

#### Scenario: One line per judged call
- **WHEN** a call is re-evaluated once after a policy change
- **THEN** exactly one audit line exists for it
