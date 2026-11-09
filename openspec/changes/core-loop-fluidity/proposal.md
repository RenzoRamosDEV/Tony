## Why

An independent review of the core loop found four places where blocking or wasted work sits on hot paths: audio-device discovery blocks the asyncio core loop for up to 5 s, speech-to-text runs on utterances whose session was already cancelled, every model turn retains every streamed SDK message, and reading one skill body re-parses every skill. Fixing them makes Tony more responsive without changing any behavior.

## What Changes

- Audio-device discovery (`pw-dump`, 5 s timeout) runs off the core event loop in a tracked background task; concurrent `list_devices` commands share one in-flight discovery; late or superseded results are dropped. The published `audio_devices` event is unchanged.
- The speech-to-text worker skips utterances whose listening session is no longer current before running inference, and drops queued utterances of ended sessions. The post-inference check stays; each session still ends exactly once.
- The Claude engine accumulates the outcome incrementally (latest assistant text, final result) instead of retaining all SDK messages; `outcome_from_messages` and token callbacks keep their behavior.
- `read_skill_body` parses only the requested skill file; full enumeration remains for the prompt listing and the unknown-name diagnostic. Path-traversal safety and fresh disk reads are preserved.
- No feature, tool, event type or config key is removed or renamed.

## Capabilities

### New Capabilities
- `audio-devices`: asynchronous, shared, cancellation-safe discovery of audio devices behind the `list_devices` command.

### Modified Capabilities
- `voice-io`: cancelled listening sessions never reach speech-to-text inference.

## Impact

- Code: `tony/core/orchestrator/runtime.py`, `tony/core/voice/listener.py`, `tony/core/orchestrator/claude_engine.py`, `tony/core/loader/skills.py`.
- Events/API: none changed. Dependencies: none.
