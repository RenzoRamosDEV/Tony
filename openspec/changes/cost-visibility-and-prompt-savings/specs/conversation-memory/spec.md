## ADDED Requirements

### Requirement: Preferences are written once
Saving a preference whose text, after whitespace normalisation and secret masking, equals an existing `- ` line of `memory/preferences.md` (case-sensitive) SHALL leave the file unchanged. A different text SHALL still be appended. Existing file content SHALL never be rewritten or deduplicated by this behavior.

#### Scenario: Duplicate preference
- **WHEN** the file contains `- Prefiero respuestas cortas` and the same preference is saved again
- **THEN** the file is unchanged

#### Scenario: Different case
- **WHEN** `- prefiero respuestas cortas` is saved while `- Prefiero respuestas cortas` exists
- **THEN** the new line is appended
