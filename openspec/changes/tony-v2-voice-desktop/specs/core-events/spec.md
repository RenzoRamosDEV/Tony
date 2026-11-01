# Spec Delta

## MODIFIED Requirements

### Requirement: Conversation event types
For the conversation and session the core SHALL publish: `token` {agent, text}; `progress` {agent, text}; `result` (see Result events); `error` {source, message}; `auth` {state, reason, retry_in_s}; `reply_mode` {mode}; `turn_started` {agent, origin, reply_mode, speaks, writes}; `transcript` {text}; `voice_state` {state, reason}. The type `audio_chunk` stays reserved and MUST NOT be published: audio never leaves the core.

#### Scenario: Token event fields
- **WHEN** Jarvis streams the text `Hola`
- **THEN** the event is `{"type": "token", "ts": "<ts>", "agent": "jarvis", "text": "Hola"}`

#### Scenario: Turn started fields
- **WHEN** the user says «Hola» with reply mode `auto` and voice ready
- **THEN** before any `token` of that turn the event `{"type": "turn_started", "ts": "<ts>", "agent": "jarvis", "origin": "voice", "reply_mode": "auto", "speaks": true, "writes": false}` is published

#### Scenario: No audio events
- **WHEN** a reply is spoken
- **THEN** no event of type `audio_chunk` is published

## ADDED Requirements

### Requirement: Voice state event
A `voice_state` event SHALL be published whenever the voice state changes, with `state` one of `loading`, `ready`, `listening`, `unavailable` and `reason` (a text for `unavailable`, otherwise `null`).

#### Scenario: Listening and back
- **WHEN** voice is ready and a listening session starts and ends with an utterance
- **THEN** `voice_state` events with `state` `listening` and then `ready` (both with `reason: null`) are published
