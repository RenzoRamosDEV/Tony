## ADDED Requirements

### Requirement: Conversation management commands
The core SHALL accept `ListConversations`, `ResumeConversation{id}` and `DeleteConversation{id}` UI commands, validated like other commands. `ListConversations` SHALL publish `conversations{items}` with the list entries (`id`, `title`, `message_count`, `last_ts`). `DeleteConversation` SHALL publish the refreshed `conversations` event. An unknown id on resume or delete SHALL publish an `error` event naming the command and change nothing.

#### Scenario: List
- **WHEN** `ListConversations` is sent and two conversations are stored
- **THEN** one `conversations` event is published with two items, newest first

#### Scenario: Resume
- **WHEN** `ResumeConversation` with a stored id is sent
- **THEN** later messages are stored under that id and no `token`, `result` or confirmation event is published by the resume itself

#### Scenario: Unknown id
- **WHEN** `ResumeConversation` with an unknown id is sent
- **THEN** an `error` event is published and the current conversation id is unchanged

#### Scenario: Extra fields rejected
- **WHEN** `ResumeConversation` is sent without `id`
- **THEN** parsing fails with an error naming the type and field

### Requirement: Conversations event
The event `conversations` SHALL carry `items`, a list of `{id, title, message_count, last_ts}`, with the standard envelope. Existing event types and fields MUST NOT change.

#### Scenario: Event shape
- **WHEN** the event is built for one conversation
- **THEN** it equals `{"type": "conversations", "ts": "<ts>", "items": [{"id": "<id>", "title": "<title>", "message_count": 2, "last_ts": "<ts>"}]}`
