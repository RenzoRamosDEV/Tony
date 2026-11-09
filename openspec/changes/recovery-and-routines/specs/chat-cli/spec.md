## ADDED Requirements

### Requirement: Chat runs the routine scheduler
While `tony chat` runs it SHALL run the routine scheduler, stopping it when the chat ends. Routine runs SHALL NOT interrupt message handling and SHALL NOT print the model's reply into the conversation.

#### Scenario: Due routine during chat
- **WHEN** a routine becomes due while the chat is waiting for input
- **THEN** a run record is created and the chat input is unaffected

#### Scenario: Chat ends
- **WHEN** the user types `/salir`
- **THEN** the scheduler stops before the process exits
