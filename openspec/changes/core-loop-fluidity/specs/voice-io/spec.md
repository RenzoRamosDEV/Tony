## ADDED Requirements

### Requirement: Cancelled utterances are not transcribed
The speech-to-text stage SHALL check that an utterance's listening session is still the current one before running inference, and SHALL discard it without transcribing when the session was stopped or cancelled. The check after inference SHALL remain. Each session SHALL still end exactly once.

#### Scenario: Cancelled before inference
- **WHEN** an utterance is queued for transcription and the session is cancelled before the stage dequeues it
- **THEN** speech-to-text is not run, no transcript is delivered, and the session ends exactly once

#### Scenario: Cancelled during inference
- **WHEN** the session is cancelled while inference is already running
- **THEN** the transcript is discarded and the session ends exactly once
