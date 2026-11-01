# Spec Delta

## ADDED Requirements

### Requirement: Voice level event
While a listening session captures audio or synthesised speech is playing, the core SHALL publish `voice_level` {source, level} about every 50 ms: `source` is `input` (microphone) or `output` (speech), `level` is the RMS of the latest audio divided by 0.2, clamped to 0..1 and rounded to two decimals. No `voice_level` SHALL be published otherwise. It carries numbers only, never audio samples.

#### Scenario: Levels while listening
- **WHEN** a listening session captures 1 s of audio
- **THEN** between 15 and 25 `voice_level` events with `source: "input"` and a `level` between 0 and 1 are published

#### Scenario: Levels while speaking
- **WHEN** a sentence of 1 s is played
- **THEN** `voice_level` events with `source: "output"` are published while it plays and none after it ends or is stopped

#### Scenario: Silent when idle
- **WHEN** voice is `ready` and neither listening nor playing
- **THEN** no `voice_level` event is published

#### Scenario: Level fields
- **WHEN** the latest microphone window has an RMS of 0.05
- **THEN** the event is `{"type": "voice_level", "ts": "<ts>", "source": "input", "level": 0.25}`
