## ADDED Requirements

### Requirement: Tool results are size-capped for the model
The text of a successful tool result returned to the model SHALL be at most `tool_result_max_chars` characters (policy `limits`, integer, default 20000, `0` disables the cap). A longer text SHALL be cut to the first `tool_result_max_chars` characters followed by `\n[truncated: showing first N of TOTAL characters]`, with N and TOTAL replaced by the numbers. The task log SHALL still record the complete masked result. Results flagged as errors SHALL NOT be truncated. The cap SHALL apply after secret masking.

#### Scenario: Large result cut
- **WHEN** the cap is 20000 and a tool returns 50000 characters
- **THEN** the model receives the first 20000 characters followed by `\n[truncated: showing first 20000 of 50000 characters]` and the log holds all 50000

#### Scenario: Result at the limit
- **WHEN** a tool returns exactly 20000 characters
- **THEN** the model receives it unchanged

#### Scenario: Error result untouched
- **WHEN** a tool returns an error of 30000 characters
- **THEN** the full error text is returned

#### Scenario: Cap disabled
- **WHEN** `tool_result_max_chars` is 0 and a tool returns 50000 characters
- **THEN** the model receives all 50000
