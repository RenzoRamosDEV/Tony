## ADDED Requirements

### Requirement: Clarification wait does not trip supervision
A pending or timed-out `tony.ask_user` call SHALL NOT count as a policy denial or an unconfirmed action and SHALL NOT cancel the task by itself. It SHALL still count as one step of the agent against `max_steps_per_agent`. User cancellation or any supervisor cancellation SHALL end the wait.

#### Scenario: Timeout does not cancel
- **WHEN** a clarification times out
- **THEN** the task keeps running and the worker may finish with another approach

#### Scenario: Cancellation ends the wait
- **WHEN** the supervisor cancels the task during a clarification
- **THEN** the wait ends immediately
