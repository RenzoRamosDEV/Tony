# Spec Delta

## MODIFIED Requirements

### Requirement: Confirmation notification
When a `needs_confirmation` event arrives while the window is hidden or minimised, the app SHALL show one native notification titled `Tony — Edith` with the (masked) question. Clicking it SHALL show, restore and raise the window on the confirmation card with keyboard focus on «Denegar». No notification SHALL be shown while the window is visible and not minimised.

#### Scenario: Hidden window
- **WHEN** the window is hidden in the tray and a confirmation for `filesystem.delete_file` becomes pending
- **THEN** one notification `Tony — Edith` with the question is shown

#### Scenario: Notification clicked
- **WHEN** the user clicks that notification
- **THEN** the window is shown on the confirmation card with focus on «Denegar»

#### Scenario: Visible window
- **WHEN** a confirmation becomes pending while the window is visible
- **THEN** no notification is shown

#### Scenario: Notifications unavailable
- **WHEN** no notification service is reachable
- **THEN** an `error` event with source `notifications` is shown once and the confirmation card still works
