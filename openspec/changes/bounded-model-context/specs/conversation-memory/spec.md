## ADDED Requirements

### Requirement: History has a character budget
After the 20-message window is applied, the replayed history SHALL contain messages whose total content length is at most `history_max_chars` characters (`tony.yaml`, integer, default 12000, `0` disables). Oldest messages SHALL be dropped first, order SHALL stay chronological, and the newest earlier message SHALL always be kept: if alone it exceeds the budget it SHALL be cut to the budget and end with `[…]`. Stored history SHALL NOT be modified.

#### Scenario: Over budget
- **WHEN** 20 stored messages total 30000 characters and the budget is 12000
- **THEN** only the newest messages that fit in 12000 characters are replayed, in chronological order

#### Scenario: Single huge message
- **WHEN** the only earlier message has 50000 characters
- **THEN** it is replayed cut to the budget and ending with `[…]`

#### Scenario: Under budget
- **WHEN** the 20 messages total 3000 characters
- **THEN** all 20 are replayed unchanged

#### Scenario: Budget disabled
- **WHEN** `history_max_chars` is 0
- **THEN** all 20 messages are replayed whatever their size
