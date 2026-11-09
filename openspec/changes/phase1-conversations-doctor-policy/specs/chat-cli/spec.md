## ADDED Requirements

### Requirement: Chat resume option
`tony chat --resume [ID]` SHALL continue the stored conversation ID, or the most recent one when ID is omitted. Resuming SHALL restore messages only. An unknown ID, or no stored conversation when ID is omitted, SHALL print a `tony:` message on stderr and exit with code 2 without starting the chat. `tony chat` without the option SHALL behave as before.

#### Scenario: Resume by id
- **WHEN** conversation A is stored and the user runs `tony chat --resume A` and types a message
- **THEN** the message is stored under A and the history sent to the model contains A's earlier messages

#### Scenario: Resume latest
- **WHEN** conversations A (older) and B (newer) exist and the user runs `tony chat --resume`
- **THEN** new messages are stored under B

#### Scenario: Unknown id
- **WHEN** the user runs `tony chat --resume nope`
- **THEN** stderr starts with `tony:`, the exit code is 2 and no chat starts

#### Scenario: Permissions not restored
- **WHEN** a resumed conversation once had a confirmed tool call
- **THEN** the same call asks for confirmation again under the unchanged policy

### Requirement: Conversations command
`tony conversations list` SHALL print the table `id | title | messages | last` newest first (20 rows). `tony conversations search TEXT` SHALL print the same table for matching conversations. `tony conversations delete ID` SHALL remove that conversation's messages and print a confirmation line. An unknown ID on delete SHALL exit 2 with a `tony:` message on stderr.

#### Scenario: List
- **WHEN** two conversations are stored and the user runs `tony conversations list`
- **THEN** stdout is a table with a header and two rows, newest first, exit code 0

#### Scenario: Search without matches
- **WHEN** no message contains the text
- **THEN** stdout contains only the table header and the exit code is 0

#### Scenario: Delete
- **WHEN** the user runs `tony conversations delete A`
- **THEN** A's messages are gone, other conversations are untouched and the exit code is 0

#### Scenario: Delete unknown
- **WHEN** the user runs `tony conversations delete nope`
- **THEN** the exit code is 2 and nothing is removed
