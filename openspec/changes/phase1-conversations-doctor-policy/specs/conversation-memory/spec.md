## ADDED Requirements

### Requirement: List conversations
`HistoryStore.list_conversations(limit=20)` SHALL return conversations newest first (by last message), each entry with `id`, `title` (the first user message cut to 60 characters), `message_count` and `last_ts` (timestamp of the last message). Content SHALL be the masked stored text.

#### Scenario: Newest first with title
- **WHEN** conversation A has 2 messages starting with a 70-character user message and conversation B, written later, has 1 message
- **THEN** the result is `[B, A]`, A's title is the first 60 characters, A's `message_count` is 2

#### Scenario: Limit
- **WHEN** 25 conversations exist and `limit` is not given
- **THEN** 20 entries are returned

#### Scenario: Empty store
- **WHEN** no messages are stored
- **THEN** the result is an empty list

### Requirement: Search conversations
`HistoryStore.search_conversations(text, limit=20)` SHALL return, in the list entry shape and newest first, the conversations having at least one message whose masked content contains `text` as a case-insensitive substring, including non-ASCII letters.

#### Scenario: Case-insensitive match
- **WHEN** a conversation contains `Compra de CAFÉ` and the search text is `café`
- **THEN** that conversation is returned once, even if several of its messages match

#### Scenario: Masked content only
- **WHEN** a message contained a secret from `config/.env` that was masked on storage and the search text is that secret
- **THEN** no conversation is returned

#### Scenario: Empty search text
- **WHEN** the search text is empty
- **THEN** the result is an empty list

### Requirement: Delete conversation
`HistoryStore.delete_conversation(id)` SHALL remove all messages of that conversation and nothing else, and return whether any message was removed.

#### Scenario: Only that conversation
- **WHEN** conversations A and B exist and A is deleted
- **THEN** A has no messages, B is unchanged and the call returns true

#### Scenario: Unknown id
- **WHEN** the id has no messages
- **THEN** the call returns false and the store is unchanged

### Requirement: Resume a conversation
Resuming a conversation SHALL set the conversation id used for new messages to the resumed id. It MUST NOT replay messages by itself, change the history budget (last 20 messages, `history_max_chars`), or restore permissions, pending approvals, unlock state or tool execution. A turn already running SHALL keep the id it started with.

#### Scenario: Next turn continues the conversation
- **WHEN** conversation A with 3 messages is resumed and the user writes a new message
- **THEN** the turn's history is A's last messages (at most 20) and the new messages are stored under A

#### Scenario: Nothing else restored
- **WHEN** a conversation that once had an allow-always answer is resumed
- **THEN** no policy, session or confirmation state changes
