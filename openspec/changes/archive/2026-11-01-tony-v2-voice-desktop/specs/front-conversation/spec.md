# Spec Delta

## MODIFIED Requirements

### Requirement: Reply mode
The reply mode SHALL be one of `auto`, `voice`, `text`, `both`. Its initial value SHALL be the last `reply_mode: <mode>` line of `memory/preferences.md` when present and valid, otherwise `reply_mode` from `config/tony.yaml`. Changing it from the UI or with `set_reply_mode({mode})` SHALL persist it and emit a `reply_mode` event. The mode applied to a message SHALL decide whether its reply is spoken and written (see voice-conversation).

#### Scenario: Mode set by phrase
- **WHEN** the user says `contéstame solo por texto` and Jarvis calls `set_reply_mode` with `{"mode": "text"}`
- **THEN** `memory/preferences.md` contains exactly one `reply_mode:` line, `reply_mode: text`, and a `reply_mode` event with mode `text` is emitted

#### Scenario: Mode replaced, not duplicated
- **WHEN** `preferences.md` contains `reply_mode: text` and the mode is set to `both`
- **THEN** that line becomes `reply_mode: both` and the other lines are unchanged

#### Scenario: Invalid mode
- **WHEN** Jarvis calls `set_reply_mode` with `{"mode": "loud"}`
- **THEN** it receives an error result listing the valid modes and nothing is written

#### Scenario: Initial mode from preferences
- **WHEN** `config/tony.yaml` has `reply_mode: auto` and `preferences.md` contains `reply_mode: voice`
- **THEN** the initial reply mode is `voice`

#### Scenario: Mode fixed for the turn
- **WHEN** a turn starts in `voice` and Jarvis calls `set_reply_mode` with `{"mode": "text"}` during it
- **THEN** that turn keeps speaking and the next message applies `text`

## ADDED Requirements

### Requirement: Turn start announced
Each front-agent turn SHALL publish, before its first `token`, one `turn_started` event with the front agent's name, the message origin (`text` or `voice`), the applied reply mode and the resulting `speaks` and `writes`. `token` events SHALL still be published for every turn.

#### Scenario: Typed message
- **WHEN** the user types `Hola` with persisted mode `both` and voice ready
- **THEN** `turn_started` has `origin: "text"`, `reply_mode: "both"`, `speaks: true`, `writes: true`, followed by the turn's `token` events

#### Scenario: Terminal chat
- **WHEN** `tony chat` answers a message with persisted mode `voice`
- **THEN** the turn has `speaks: false` and `writes: true` and the reply is printed
