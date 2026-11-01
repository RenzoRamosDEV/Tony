# conversation-memory Specification

## Purpose
Defines Tony's local memory: the user preferences file injected into the front agent's prompt and the SQLite conversation history from which the recent messages are sent to the model.

## Requirements

### Requirement: Preferences injected into the front prompt
The content of `memory/preferences.md` SHALL be read at the start of every front-agent turn and appended to the front agent's system prompt under the heading `## Preferencias del usuario`, with secret values masked. A missing or empty file SHALL add nothing. Manual edits SHALL apply from the next turn without restarting.

#### Scenario: Preferences present
- **WHEN** `memory/preferences.md` contains `- Llámame por mi nombre: Renzo`
- **THEN** the front agent's system prompt ends with `## Preferencias del usuario` followed by that line

#### Scenario: Manual edit picked up
- **WHEN** the user edits `preferences.md` between two messages
- **THEN** the second turn's system prompt contains the edited content

#### Scenario: Missing file
- **WHEN** `memory/preferences.md` does not exist
- **THEN** the system prompt is the agent's `agent.md` body alone

### Requirement: Conversation history storage
Every user message and every completed front-agent reply SHALL be stored in `memory/conversations.sqlite` (created with its folder when missing) in a `messages` table with `conversation_id`, `role` (`user` or `assistant`), `agent`, `content` (secrets masked) and `ts` (UTC ISO 8601). A new conversation id SHALL be created each time `tony chat` or the desktop app starts. Worker results MUST NOT be stored as messages.

#### Scenario: Turn stored
- **WHEN** the user writes `Hola` and Jarvis answers `Buenas tardes, señor.`
- **THEN** two rows exist for the conversation: `user`/`jarvis`/`Hola` and `assistant`/`jarvis`/`Buenas tardes, señor.`

#### Scenario: Failed turn
- **WHEN** the model fails before completing a reply
- **THEN** the user message is stored and no assistant row is added

### Requirement: History sent to the model
Each front-agent turn SHALL include, oldest first, the last 20 stored messages of the current conversation that precede the current message. Messages of earlier conversations MUST NOT be included.

#### Scenario: Window of 20
- **WHEN** the current conversation already has 25 messages and the user writes a new one
- **THEN** the turn includes the 20 most recent earlier messages in chronological order and not the new message twice

#### Scenario: New conversation
- **WHEN** the app is restarted and the user writes the first message
- **THEN** the turn includes no history
