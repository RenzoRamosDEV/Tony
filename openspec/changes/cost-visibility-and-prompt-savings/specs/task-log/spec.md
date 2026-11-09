## ADDED Requirements

### Requirement: Token usage carries cache and cost data
Each `token_usage` log event SHALL keep its `input_tokens` and `output_tokens` and SHALL additionally carry `cache_read_tokens` and `cache_creation_tokens` (integers, 0 when the model reports none) and `cost_usd` (number, or `null` when the SDK did not report a cost). A missing cost SHALL never be written as 0.

#### Scenario: Cache and cost reported
- **WHEN** the SDK result reports `cache_read_input_tokens: 900`, `cache_creation_input_tokens: 100` and `total_cost_usd: 0.012`
- **THEN** the `token_usage` event has `cache_read_tokens: 900`, `cache_creation_tokens: 100` and `cost_usd: 0.012`

#### Scenario: Cost not reported
- **WHEN** the SDK result has no `total_cost_usd`
- **THEN** the `token_usage` event has `cost_usd: null`
