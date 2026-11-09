## ADDED Requirements

### Requirement: Confirmation wording is reused
A confirmation question accepted by the format check SHALL be remembered in memory for the process lifetime, keyed by tool id, masked args preview, rule id, the wording system prompt and the model id, holding at most 128 entries with least-recently-used eviction. An identical later question SHALL reuse the remembered text without calling the model. Empty, invalid, timed-out or failed wording SHALL NOT be remembered. Permission verdicts SHALL NOT be remembered and SHALL be evaluated for every call.

#### Scenario: Same question twice
- **WHEN** the same tool, masked args and rule need confirmation twice and the first wording was valid
- **THEN** the model is called once and both questions are identical

#### Scenario: Invalid wording not remembered
- **WHEN** the model returns `¿Puedo borrar el archivo?` and the same confirmation is needed again
- **THEN** the model is called again

#### Scenario: Different arguments
- **WHEN** the same tool is confirmed with different masked args
- **THEN** the model is called for each
