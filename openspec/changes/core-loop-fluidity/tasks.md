## 1. Skip cancelled transcription (voice-io)
- [x] 1.1 Write failing tests: utterance queued then session cancelled is not transcribed and ends once; cancel during inference discards transcript and ends once
- [x] 1.2 Implement the pre-inference session check in `Listener._transcribe`; refactor

## 2. Incremental outcome accumulation
- [x] 2.1 Write failing tests for `OutcomeAccumulator` (text, error, missing result, usage, structured output) and that `run`/`converse` do not retain all messages
- [x] 2.2 Implement the accumulator, delegate `outcome_from_messages` to it, use it in `ClaudeEngine`

## 3. Single skill read
- [x] 3.1 Write failing tests: only the requested file is parsed; traversal names and invalid skills return `None`; fresh read after edit
- [x] 3.2 Implement direct lookup in `read_skill_body`

## 4. Off-loop device discovery (audio-devices)
- [x] 4.1 Write failing tests with a fake slow query: loop stays responsive, concurrent requests share one query, shutdown drops the late result
- [x] 4.2 Implement the tracked, shared background discovery in `runtime.py`; keep the `audio_devices` event shape

## 5. Verification
- [x] 5.1 Run the full test suite and mutation testing on the diff (>95 %, abort at 3 min)
